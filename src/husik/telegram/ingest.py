"""Telegram PDF 수신 -> PDF 분석 -> 사건 묶기 -> Telegram/Notion 반영 파이프라인.

이 모듈은 "workflow는 Success인데 아무 반응이 없는" 상태를 없애기 위해
모든 단계에서 카운터를 남기고(IngestStats), 허용된 사용자가 PDF를 보내면
반드시 성공/실패/스킵 중 하나의 메시지를 개인대화방으로 돌려준다.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path

from husik.auction.monitor import enrich_case
from husik.blog.monitor import find_new_posts, is_within_days
from husik.config import Config
from husik.notion.client import NotionClient
from husik.notion.schema import resolve_database_id
from husik.notion.upsert import NotionCaseData, upsert_case_page
from husik.pdf.detect_cases import (
    AnalyzedPdf,
    CaseRecord,
    PageAnalysis,
    analyze_page,
    analyze_pdf_pages,
)
from husik.pdf.render import render_pdf_to_images
from husik.pdf.segment import REVIEW_LABEL, ImageSegment
from husik.state.store import CaseState, StateStore
from husik.telegram.client import TelegramClient, TelegramError
from husik.telegram.commands import handle_bot_command
from husik.telegram.links import private_channel_message_link
from husik.telegram.templates import (
    AuctionFields,
    CaseMessageData,
    InterestStats,
    build_page_caption,
    build_representative_message,
)
from husik.utils.text import RATING_UNKNOWN

logger = logging.getLogger(__name__)

MAX_ALBUM_SIZE = 10
MAX_PDF_BYTES = 20 * 1024 * 1024  # Telegram Bot API 파일 다운로드 제한
MIN_TEXT_FOR_OCR_SUCCESS = 5  # 이 미만이면 사실상 OCR이 아무 것도 못 읽은 것으로 간주

DOWNLOAD_FAIL_MSG = "PDF 다운로드에 실패했습니다. 파일 크기 또는 텔레그램 파일 접근을 확인하세요."
OCR_FAIL_MSG = "PDF 분석에 실패했습니다. 이미지 품질 또는 OCR 설정을 확인하세요."
NO_CASE_MSG = "처리 완료: 사건번호를 찾지 못했습니다. OCR/Vision 분석 개선이 필요합니다."
CHANNEL_FAIL_MSG = "텔레그램 채널 전송 실패: 채널 ID 또는 봇 관리자 권한을 확인하세요."
NOTION_FAIL_MSG = (
    "텔레그램 전송은 완료됐지만 노션 업데이트에 실패했습니다. Integration 연결 또는 DB URL을 확인하세요."
)
DUPLICATE_MSG = "이미 처리된 PDF입니다 (중복)."
GENERIC_FAIL_MSG = "PDF 처리 중 오류가 발생했습니다."


class OcrAnalysisError(Exception):
    """OCR/텍스트 추출이 전면적으로 실패했을 때(모든 페이지가 텍스트를 전혀 못 읽음)."""


class ChannelSendError(TelegramError):
    """대표 메시지 전송(출력 채널) 자체가 실패했을 때."""


@dataclass
class IngestStats:
    webhook_deleted_or_absent: int = 0
    updates_seen: int = 0
    messages_seen: int = 0
    channel_posts_seen: int = 0
    documents_seen: int = 0
    pdf_documents_seen: int = 0
    allowed_user_passed: int = 0
    skipped_by_user: int = 0
    downloaded_pdfs: int = 0
    duplicate_pdfs_skipped: int = 0
    pages_rendered: int = 0
    detected_cases: int = 0
    filtered_cases: int = 0
    sent_telegram_cases: int = 0
    sent_telegram_images: int = 0
    notion_upserted: int = 0
    user_notifications_sent: int = 0
    errors_count: int = 0
    # 필수 수정 8: 스킵 사유 세분화 (위 필수 카운터에 더한 보조 지표)
    no_case_number_pdfs: int = 0
    no_rating_cases: int = 0
    ocr_failed_pdfs: int = 0

    def log_summary(self) -> None:
        logger.info("===== husik pdf ingest summary =====")
        for f in fields(self):
            logger.info("PDF_INGEST_STAT %s=%s", f.name, getattr(self, f.name))
        logger.info("=====================================")


@dataclass
class CaseProcessResult:
    case_number: str
    rating: str
    title: str
    sale_date: date | None
    page_start: int
    page_end: int
    image_count: int
    processed: bool
    reason: str = ""
    page_image_map: str = ""
    image_refs: list[str] = field(default_factory=list)
    mixed_page: bool = False


@dataclass
class CaseOutcome:
    case_number: str
    telegram_sent: bool = False
    images_sent: int = 0
    images_failed: int = 0
    notion_attempted: bool = False
    notion_sent: bool = False


@dataclass
class PdfRunResult:
    detected_cases: int = 0
    channel_send_failed: bool = False
    ocr_failed: bool = False
    cases_sent: int = 0
    images_sent: int = 0
    images_failed: int = 0
    notion_upserted: int = 0
    any_notion_failed: bool = False
    case_results: list[CaseProcessResult] = field(default_factory=list)


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def analyze_pdf(pdf_path: Path, work_dir: Path, openai_api_key: str | None) -> AnalyzedPdf:
    rendered_pages = render_pdf_to_images(pdf_path, work_dir)
    analyses: list[PageAnalysis] = [analyze_page(p, openai_api_key) for p in rendered_pages]
    return analyze_pdf_pages(rendered_pages, analyses, work_dir)


def _format_page_image_refs(record: CaseRecord) -> list[str]:
    """디버그 출력용: ["p1 crop1", "p2 crop1"] 형태로 반환한다."""
    counts: dict[int, int] = {}
    refs: list[str] = []
    for seg in record.image_segments:
        counts[seg.page_no] = counts.get(seg.page_no, 0) + 1
        refs.append(f"p{seg.page_no} crop{counts[seg.page_no]}")
    return refs


def dry_run_report(records: list[CaseRecord]) -> list[CaseProcessResult]:
    """사건번호가 감지된 사건은 등급과 무관하게 전부 전송 대상이다 (정책: 필터 아님, 분류만)."""
    results = []
    for r in records:
        results.append(
            CaseProcessResult(
                case_number=r.case_number,
                rating=r.rating,
                title=r.title,
                sale_date=r.sale_date,
                page_start=r.page_start,
                page_end=r.page_end,
                image_count=len(r.image_segments),
                processed=True,
                reason="",
                page_image_map=", ".join(_format_page_image_refs(r)),
                image_refs=_format_page_image_refs(r),
                mixed_page=r.mixed_page_used,
            )
        )
    return results


def build_result_notifications(result: PdfRunResult) -> list[str]:
    """PdfRunResult로부터 사용자 개인대화방에 보낼 메시지 목록을 만든다.

    항상 최소 1개의 메시지를 반환한다 (완전 무반응 상태 방지).
    """
    if result.ocr_failed:
        return [OCR_FAIL_MSG]
    if result.channel_send_failed:
        return [CHANNEL_FAIL_MSG]
    if result.detected_cases == 0:
        return [NO_CASE_MSG]

    notes: list[str] = []
    if result.any_notion_failed:
        notes.append(NOTION_FAIL_MSG)
    notes.append(
        f"처리 완료: 사건번호 {result.detected_cases}개 감지, {result.cases_sent}건 전송, "
        f"{result.images_sent}개 이미지 생성, 노션 {result.notion_upserted}건 업데이트"
    )
    if result.images_failed:
        notes.append(f"이미지 일부 전송 실패: {result.images_failed}장 (텔레그램 전송 오류)")
    return notes


def _compress_for_retry(path: Path, max_dim: int = 1280, quality: int = 70) -> Path:
    from PIL import Image

    with Image.open(path) as img:
        img = img.convert("RGB")
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
            img = img.resize(new_size, Image.LANCZOS)
        out_path = path.with_name(f"{path.stem}_retry.jpg")
        img.save(out_path, "JPEG", quality=quality, optimize=True)
    return out_path


def send_photo_with_fallback(
    telegram: TelegramClient,
    channel_id: str,
    path: Path,
    caption: str,
    reply_to_message_id: int | None,
) -> int | None:
    """실패해도 예외를 던지지 않고 None을 반환한다 (호출자가 실패 카운트만 하면 됨)."""
    try:
        sent = telegram.send_photo(channel_id, path, caption=caption, reply_to_message_id=reply_to_message_id)
        return sent["message_id"]
    except TelegramError as exc:
        logger.warning("send_photo failed for %s, retrying with compression: %s", path.name, exc)

    compressed: Path | None = None
    try:
        compressed = _compress_for_retry(path)
        sent = telegram.send_photo(channel_id, compressed, caption=caption)
        return sent["message_id"]
    except Exception as exc:
        logger.warning("send_photo retry (compressed) failed for %s: %s", path.name, exc)
        return None
    finally:
        if compressed is not None:
            compressed.unlink(missing_ok=True)


def _send_image_chunk(
    telegram: TelegramClient,
    channel_id: str,
    chunk: list[Path],
    captions: list[str],
    reply_to_message_id: int,
) -> tuple[list[int], int]:
    if len(chunk) == 1:
        msg_id = send_photo_with_fallback(telegram, channel_id, chunk[0], captions[0], reply_to_message_id)
        return ([msg_id], 0) if msg_id is not None else ([], 1)

    try:
        result = telegram.send_media_group(
            channel_id, chunk, captions, reply_to_message_id=reply_to_message_id
        )
        return [item["message_id"] for item in result if "message_id" in item], 0
    except TelegramError as exc:
        logger.warning("media group with reply failed, retrying without reply: %s", exc)

    try:
        result = telegram.send_media_group(channel_id, chunk, captions)
        return [item["message_id"] for item in result if "message_id" in item], 0
    except TelegramError as exc:
        logger.warning("media group failed entirely, falling back to per-photo sendPhoto: %s", exc)

    ids: list[int] = []
    failed = 0
    for path, caption in zip(chunk, captions, strict=False):
        msg_id = send_photo_with_fallback(telegram, channel_id, path, caption, None)
        if msg_id is None:
            failed += 1
        else:
            ids.append(msg_id)
    return ids, failed


@dataclass
class _CaseTelegramResult:
    representative_message_id: int
    image_message_ids: list[int]
    images_failed: int


def _continue_header(case_number: str, continuation_index: int) -> str:
    if continuation_index <= 1:
        return f"[{case_number}-계속]"
    return f"[{case_number}-계속 {continuation_index}]"


def send_case_to_telegram(
    telegram: TelegramClient, channel_id: str, record: CaseRecord, message_text: str
) -> _CaseTelegramResult:
    try:
        sent = telegram.send_message(channel_id, message_text)
    except TelegramError as exc:
        raise ChannelSendError(str(exc)) from exc
    rep_id = sent["message_id"]

    image_ids: list[int] = []
    images_failed = 0
    segments = record.image_segments
    continuation_index = 1
    for start in range(0, len(segments), MAX_ALBUM_SIZE):
        chunk_segments = segments[start : start + MAX_ALBUM_SIZE]
        chunk_paths = [seg.image_path for seg in chunk_segments]
        captions = [build_page_caption(seg.page_no) for seg in chunk_segments]

        reply_id = rep_id
        if start > 0:
            header_text = _continue_header(record.case_number, continuation_index)
            followup = telegram.send_message(channel_id, header_text)
            reply_id = followup["message_id"]
            continuation_index += 1

        sent_ids, failed = _send_image_chunk(telegram, channel_id, chunk_paths, captions, reply_id)
        image_ids.extend(sent_ids)
        images_failed += failed
    return _CaseTelegramResult(
        representative_message_id=rep_id, image_message_ids=image_ids, images_failed=images_failed
    )


def _to_message_data(record: CaseRecord, auction_info, interest: InterestStats) -> CaseMessageData:
    sale_date = record.sale_date or auction_info.sale_date
    auction = AuctionFields(
        court=auction_info.court or "확인중",
        address=auction_info.address or "확인중",
        appraisal_price=auction_info.appraisal_price,
        min_price=auction_info.min_price,
        sale_date=sale_date,
        status=auction_info.status or "확인중",
        winning_price=auction_info.winning_price,
        winning_rate=auction_info.winning_rate,
        bidder_count=auction_info.bidder_count,
        madangs_link=auction_info.madangs_link or "확인중",
        court_link=auction_info.court_link or "확인중",
    )
    return CaseMessageData(
        case_number=record.case_number,
        rating=record.rating or RATING_UNKNOWN,
        title=record.title,
        sale_date_text=record.sale_date,
        auction=auction,
        interest=interest,
        image_count=len(record.image_segments),
    )


def _process_single_case(
    record: CaseRecord,
    config: Config,
    state: StateStore,
    telegram: TelegramClient,
    notion_client: NotionClient | None,
    database_id: str | None,
) -> CaseOutcome:
    outcome = CaseOutcome(case_number=record.case_number)
    existing = state.get_case(record.case_number)
    auction_info = enrich_case(record.case_number, config)

    known_urls = set(existing.blog_urls) if existing else set()
    new_posts = []
    if config.blog_monitor_enabled:
        new_posts = find_new_posts(
            config.naver_client_id,
            config.naver_client_secret,
            record.case_number,
            record.title,
            auction_info.address or "",
            known_urls,
        )
    blog_urls = list(known_urls) + [p.link for p in new_posts]
    recent_count = sum(1 for p in new_posts if is_within_days(p.post_date, 7))

    interest = InterestStats(
        court_views=auction_info.court_views,
        madangs_views=auction_info.madangs_views,
        blog_mentions=len(blog_urls),
        recent_blog_mentions=recent_count,
    )
    message_data = _to_message_data(record, auction_info, interest)
    text = build_representative_message(message_data)

    # ChannelSendError는 여기서 잡지 않고 호출자(process_pdf_and_send)로 전파한다.
    send_result = send_case_to_telegram(telegram, config.telegram_auction_channel_id, record, text)
    outcome.telegram_sent = True
    outcome.images_sent = len(send_result.image_message_ids)
    outcome.images_failed = send_result.images_failed

    message_link = private_channel_message_link(
        config.telegram_auction_channel_id, send_result.representative_message_id
    )

    sale_date = auction_info.sale_date
    case_state = CaseState(
        case_number=record.case_number,
        channel_id=config.telegram_auction_channel_id,
        representative_message_id=send_result.representative_message_id,
        image_message_ids=send_result.image_message_ids,
        rating=record.rating,
        title=record.title,
        status=auction_info.status or "확인중",
        blog_urls=blog_urls,
        auction_info={
            "court": auction_info.court,
            "address": auction_info.address,
            "appraisal_price": auction_info.appraisal_price,
            "min_price": auction_info.min_price,
            "sale_date": sale_date.isoformat() if sale_date else None,
            "status": auction_info.status,
            "winning_price": auction_info.winning_price,
            "winning_rate": auction_info.winning_rate,
            "bidder_count": auction_info.bidder_count,
            "court_views": auction_info.court_views,
            "madangs_views": auction_info.madangs_views,
            "madangs_link": auction_info.madangs_link,
            "court_link": auction_info.court_link,
        },
    )

    if notion_client:
        outcome.notion_attempted = True
        if database_id:
            try:
                notion_data = NotionCaseData(
                    case_number=record.case_number,
                    title=record.title,
                    rating=record.rating or RATING_UNKNOWN,
                    item_number="확인중",
                    court=auction_info.court or "확인중",
                    address=auction_info.address or "확인중",
                    appraisal_price=auction_info.appraisal_price,
                    min_price=auction_info.min_price,
                    sale_date=auction_info.sale_date,
                    status=auction_info.status or "확인중",
                    winning_price=auction_info.winning_price,
                    winning_rate=auction_info.winning_rate,
                    bidder_count=auction_info.bidder_count,
                    court_views=auction_info.court_views,
                    madangs_views=auction_info.madangs_views,
                    blog_mentions=len(blog_urls),
                    recent_blog_mentions=recent_count,
                    madangs_link=auction_info.madangs_link or "확인중",
                    court_link=auction_info.court_link or "확인중",
                    telegram_message_link=message_link,
                )
                page_id = upsert_case_page(notion_client, database_id, notion_data, log_lines=[text])
                case_state.notion_page_id = page_id
                outcome.notion_sent = True
            except Exception:
                logger.exception("notion upsert failed for %s", record.case_number)
        else:
            logger.error("notion database_id를 확보하지 못해 %s upsert를 건너뜁니다", record.case_number)

    state.upsert_case(case_state)
    state.save()
    return outcome


def process_pdf_and_send(
    pdf_path: Path, config: Config, state: StateStore, tmp_root: Path, stats: IngestStats
) -> PdfRunResult:
    """실제 Telegram/Notion 반영까지 수행하고, 사용자 알림에 필요한 결과를 돌려준다."""
    result = PdfRunResult()
    work_dir = tmp_root / f"work_{hash_file(pdf_path)[:12]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        rendered_pages = render_pdf_to_images(pdf_path, work_dir)
        stats.pages_rendered += len(rendered_pages)
        analyses = [analyze_page(p, config.openai_api_key) for p in rendered_pages]
        analyzed = analyze_pdf_pages(rendered_pages, analyses, work_dir)
        records = analyzed.records
        result.detected_cases = len(records)
        stats.detected_cases += len(records)

        if not records:
            non_empty_pages = sum(1 for a in analyses if len(a.raw_text.strip()) >= MIN_TEXT_FOR_OCR_SUCCESS)
            if rendered_pages and non_empty_pages == 0:
                stats.ocr_failed_pdfs += 1
                stats.errors_count += 1
                result.ocr_failed = True
            else:
                stats.no_case_number_pdfs += 1
            return result

        for r in records:
            if r.rating == RATING_UNKNOWN:
                stats.no_rating_cases += 1
        # 정책: 달러등급은 필터가 아니라 분류 태그. 사건번호가 감지된 사건은 등급과
        # 무관하게 전부 전송 대상이다 (filtered_cases는 detected_cases와 동일하게 유지).
        stats.filtered_cases += len(records)

        telegram = TelegramClient(config.telegram_auction_bot_token)
        notion_client = NotionClient(config.notion_token) if config.notion_token else None
        database_id = (
            resolve_database_id(notion_client, config.notion_auction_db_url) if notion_client else None
        )

        for record in records:
            try:
                outcome = _process_single_case(record, config, state, telegram, notion_client, database_id)
            except ChannelSendError:
                logger.exception("telegram channel send failed for case %s", record.case_number)
                result.channel_send_failed = True
                stats.errors_count += 1
                break
            except Exception:
                logger.exception("failed to process case %s", record.case_number)
                stats.errors_count += 1
                continue

            result.cases_sent += 1
            result.images_sent += outcome.images_sent
            result.images_failed += outcome.images_failed
            if outcome.notion_attempted:
                if outcome.notion_sent:
                    result.notion_upserted += 1
                else:
                    result.any_notion_failed = True

        # 확신이 낮아 특정 사건에 못 붙인 이미지는 절대 섞지 않고 "검토필요"로 따로 보낸다.
        if analyzed.review_segments and not result.channel_send_failed:
            try:
                _send_review_segments(telegram, config.telegram_auction_channel_id, analyzed.review_segments)
            except Exception:
                logger.exception("failed to send review segments")
                stats.errors_count += 1

        stats.sent_telegram_cases += result.cases_sent
        stats.sent_telegram_images += result.images_sent
        stats.notion_upserted += result.notion_upserted
        return result
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _send_review_segments(
    telegram: TelegramClient, channel_id: str, segments: list[ImageSegment]
) -> None:
    """사건 구분이 불확실한 이미지는 특정 사건에 붙이지 않고 별도 메시지로 보낸다.

    다른 사건 이미지와 절대 섞이면 안 되므로, 확신이 없을 땐 이렇게 따로 보내는
    쪽을 택한다 (요구사항: "확신이 낮으면 차라리 해당 이미지를 검토필요로 따로 보내세요").
    """
    pages = sorted({seg.page_no for seg in segments})
    page_list = ", ".join(f"p{p}" for p in pages)
    header = f"[검토필요] 사건 구분이 불확실한 페이지 ({page_list})"
    sent = telegram.send_message(channel_id, header, parse_mode="HTML")
    rep_id = sent["message_id"]

    paths = [seg.image_path for seg in segments]
    captions = [build_page_caption(seg.page_no) for seg in segments]
    for start in range(0, len(paths), MAX_ALBUM_SIZE):
        chunk_paths = paths[start : start + MAX_ALBUM_SIZE]
        chunk_captions = captions[start : start + MAX_ALBUM_SIZE]
        _send_image_chunk(telegram, channel_id, chunk_paths, chunk_captions, rep_id)


@dataclass
class DryRunReport:
    results: list[CaseProcessResult]
    review_page_count: int = 0


def _save_crops(analyzed: AnalyzedPdf, dest_dir: Path) -> None:
    """--save-crops 디버그 옵션: 사건별/검토필요별 crop 이미지를 지정된 폴더에 복사한다."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for record in analyzed.records:
        case_dir = dest_dir / record.case_number
        case_dir.mkdir(parents=True, exist_ok=True)
        for seg in record.image_segments:
            shutil.copy2(seg.image_path, case_dir / seg.image_path.name)

    if analyzed.review_segments:
        review_dir = dest_dir / REVIEW_LABEL
        review_dir.mkdir(parents=True, exist_ok=True)
        for seg in analyzed.review_segments:
            shutil.copy2(seg.image_path, review_dir / seg.image_path.name)


def process_pdf(
    pdf_path: Path,
    config: Config,
    state: StateStore,
    send: bool,
    tmp_root: Path,
    save_crops_dir: Path | None = None,
) -> DryRunReport:
    """CLI process-local-pdf 용. send=True면 실제 반영까지 수행한다."""
    work_dir = tmp_root / f"work_{hash_file(pdf_path)[:12]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        analyzed = analyze_pdf(pdf_path, work_dir, config.openai_api_key)
        results = dry_run_report(analyzed.records)
        review_count = len(analyzed.review_segments)

        if save_crops_dir is not None:
            _save_crops(analyzed, save_crops_dir)

        if not send:
            return DryRunReport(results=results, review_page_count=review_count)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    stats = IngestStats()
    process_pdf_and_send(pdf_path, config, state, tmp_root, stats)
    stats.log_summary()
    return DryRunReport(results=results, review_page_count=review_count)


def poll_and_ingest(config: Config, state: StateStore) -> IngestStats:
    stats = IngestStats()
    telegram = TelegramClient(config.telegram_auction_bot_token)
    tmp_root = config.tmp_dir
    tmp_root.mkdir(parents=True, exist_ok=True)

    try:
        webhook_info = telegram.get_webhook_info()
        had_webhook = bool(webhook_info.get("url"))
        telegram.delete_webhook(drop_pending_updates=False)
        stats.webhook_deleted_or_absent = 1
        logger.info(
            "webhook %s (getUpdates polling과 webhook은 동시에 쓸 수 없음)",
            "was set and has now been deleted" if had_webhook else "was already absent (정상)",
        )
    except Exception:
        logger.exception("failed to check/delete webhook before polling")
        stats.errors_count += 1

    try:
        updates = telegram.get_updates(
            offset=state.telegram_offset or None, allowed_updates=["message", "channel_post"]
        )
    except Exception:
        logger.exception("getUpdates failed")
        stats.errors_count += 1
        stats.log_summary()
        return stats

    stats.updates_seen = len(updates)
    if not updates:
        logger.info("updates_seen=0 (신규 텔레그램 update 없음)")

    for update in updates:
        update_id = update["update_id"]
        # PDF 유실 방지: 처리 전에 offset부터 올려서 저장한다. 처리가 실패해도
        # 같은 update를 무한 재시도하며 막히지 않도록 한다.
        state.telegram_offset = update_id + 1
        state.save()
        try:
            _handle_update(update, config, state, telegram, tmp_root, stats)
        except Exception:
            logger.exception("failed to handle update %s", update_id)
            stats.errors_count += 1
            _notify_generic_failure(telegram, update, stats)
        state.save()

    stats.log_summary()
    return stats


def _notify_generic_failure(telegram: TelegramClient, update: dict, stats: IngestStats) -> None:
    """update 처리 자체가 예기치 못하게 실패해도 가능하면 사용자에게 알린다."""
    try:
        message = update.get("message") or {}
        chat = message.get("chat", {})
        if chat.get("type") == "private" and chat.get("id"):
            telegram.send_message(
                chat["id"], "PDF 처리 중 예기치 못한 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            )
            stats.user_notifications_sent += 1
    except Exception:
        logger.exception("failed to notify user about generic failure")


def _handle_update(
    update: dict,
    config: Config,
    state: StateStore,
    telegram: TelegramClient,
    tmp_root: Path,
    stats: IngestStats,
) -> None:
    if update.get("channel_post") is not None:
        stats.channel_posts_seen += 1
        return

    message = update.get("message")
    if not message:
        return
    stats.messages_seen += 1

    chat = message.get("chat", {})
    from_user = message.get("from", {})
    chat_id = chat.get("id")

    text = message.get("text")
    if chat.get("type") == "private" and text and text.startswith("/"):
        response = handle_bot_command(text, from_user.get("id"), chat_id)
        if response is not None:
            try:
                telegram.send_message(chat_id, response)
                stats.user_notifications_sent += 1
            except Exception:
                logger.exception("failed to respond to bot command")
                stats.errors_count += 1
        return

    if chat.get("type") != "private":
        return

    allowed_id = config.telegram_allowed_user_id
    if not allowed_id or str(from_user.get("id")) != str(allowed_id):
        stats.skipped_by_user += 1
        logger.info("skipped message from a non-allowed user in private chat")
        return
    stats.allowed_user_passed += 1

    document = message.get("document")
    if document:
        stats.documents_seen += 1
    if not document or document.get("mime_type") != "application/pdf":
        return
    stats.pdf_documents_seen += 1

    file_id = document["file_id"]
    file_size = document.get("file_size") or 0
    if file_size and file_size > MAX_PDF_BYTES:
        telegram.send_message(chat_id, DOWNLOAD_FAIL_MSG)
        stats.user_notifications_sent += 1
        stats.errors_count += 1
        return

    pdf_path = tmp_root / f"in_{update['update_id']}.pdf"
    try:
        file_info = telegram.get_file(file_id)
        telegram.download_file(file_info["file_path"], pdf_path)
    except Exception:
        logger.exception("pdf download failed")
        telegram.send_message(chat_id, DOWNLOAD_FAIL_MSG)
        stats.user_notifications_sent += 1
        stats.errors_count += 1
        return
    stats.downloaded_pdfs += 1

    try:
        pdf_hash = hash_file(pdf_path)
        if state.has_processed_pdf(pdf_hash):
            stats.duplicate_pdfs_skipped += 1
            telegram.send_message(chat_id, DUPLICATE_MSG)
            stats.user_notifications_sent += 1
            return

        run_result = process_pdf_and_send(pdf_path, config, state, tmp_root, stats)
        # 성공 기준 = 사건번호 기준 전송 성공. 사건번호를 못 찾았거나(0건) 텔레그램
        # 전송이 실패했으면 해시를 저장하지 않아 같은 PDF를 다시 보내면 재처리된다.
        if run_result.cases_sent > 0:
            state.mark_pdf_processed(pdf_hash, {"file_name": document.get("file_name", "")})
        else:
            logger.info("pdf not marked as processed (no case successfully sent); can be retried")

        for note in build_result_notifications(run_result):
            telegram.send_message(chat_id, note)
            stats.user_notifications_sent += 1
    except Exception:
        logger.exception("pdf processing failed")
        telegram.send_message(chat_id, GENERIC_FAIL_MSG)
        stats.user_notifications_sent += 1
        stats.errors_count += 1
    finally:
        pdf_path.unlink(missing_ok=True)
