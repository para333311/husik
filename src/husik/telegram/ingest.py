"""Telegram PDF 수신 -> PDF 분석 -> 사건 묶기 -> Telegram/Notion 반영 파이프라인."""
from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from husik.auction.monitor import enrich_case
from husik.blog.monitor import find_new_posts, is_within_days
from husik.config import Config
from husik.notion.client import NotionClient, extract_database_id
from husik.notion.upsert import NotionCaseData, upsert_case_page
from husik.pdf.detect_cases import (
    CaseRecord,
    PageAnalysis,
    analyze_page,
    filter_qualified_cases,
    group_pages_into_cases,
)
from husik.pdf.render import render_pdf_to_images
from husik.state.store import CaseState, StateStore
from husik.telegram.client import TelegramClient, TelegramError
from husik.telegram.links import private_channel_message_link
from husik.telegram.templates import (
    AuctionFields,
    CaseMessageData,
    InterestStats,
    build_representative_message,
)

logger = logging.getLogger(__name__)

MAX_ALBUM_SIZE = 10
MAX_PDF_BYTES = 20 * 1024 * 1024  # Telegram Bot API 파일 다운로드 제한


@dataclass
class CaseProcessResult:
    case_number: str
    rating: str
    title: str
    page_start: int
    page_end: int
    processed: bool
    reason: str = ""


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def analyze_pdf(pdf_path: Path, work_dir: Path, openai_api_key: str | None) -> list[CaseRecord]:
    rendered_pages = render_pdf_to_images(pdf_path, work_dir)
    analyses: list[PageAnalysis] = [analyze_page(p, openai_api_key) for p in rendered_pages]
    return group_pages_into_cases(analyses)


def dry_run_report(records: list[CaseRecord]) -> list[CaseProcessResult]:
    qualified_numbers = {r.case_number for r in filter_qualified_cases(records)}
    results = []
    for r in records:
        processed = r.case_number in qualified_numbers
        reason = "" if processed else "달러등급 $$$ 미만"
        results.append(
            CaseProcessResult(
                case_number=r.case_number,
                rating=r.rating or "-",
                title=r.title,
                page_start=r.page_start,
                page_end=r.page_end,
                processed=processed,
                reason=reason,
            )
        )
    return results


def _to_message_data(record: CaseRecord, auction_info, interest: InterestStats) -> CaseMessageData:
    auction = AuctionFields(
        court=auction_info.court or "확인중",
        address=auction_info.address or "확인중",
        appraisal_price=auction_info.appraisal_price,
        min_price=auction_info.min_price,
        sale_date=auction_info.sale_date,
        status=auction_info.status or "확인중",
        winning_price=auction_info.winning_price,
        winning_rate=auction_info.winning_rate,
        bidder_count=auction_info.bidder_count,
        madangs_link=auction_info.madangs_link or "확인중",
        court_link=auction_info.court_link or "확인중",
    )
    return CaseMessageData(
        case_number=record.case_number,
        rating=record.rating or "",
        title=record.title,
        auction=auction,
        interest=interest,
        image_count=len(record.pages),
    )


def send_case_to_telegram(
    telegram: TelegramClient, channel_id: str, record: CaseRecord, message_text: str
) -> tuple[int, list[int]]:
    sent = telegram.send_message(channel_id, message_text)
    rep_id = sent["message_id"]

    image_ids: list[int] = []
    paths = record.image_paths
    for start in range(0, len(paths), MAX_ALBUM_SIZE):
        chunk = paths[start : start + MAX_ALBUM_SIZE]
        captions = [f"{p.page_no}p" for p in record.pages[start : start + MAX_ALBUM_SIZE]]
        try:
            if len(chunk) == 1:
                result = [
                    telegram.send_photo(
                        channel_id, chunk[0], caption=captions[0], reply_to_message_id=rep_id
                    )
                ]
            else:
                result = telegram.send_media_group(channel_id, chunk, captions, reply_to_message_id=rep_id)
        except TelegramError:
            logger.warning("reply-send failed, falling back to plain send for case %s", record.case_number)
            if len(chunk) == 1:
                result = [telegram.send_photo(channel_id, chunk[0], caption=captions[0])]
            else:
                result = telegram.send_media_group(channel_id, chunk, captions)
        for item in result:
            if "message_id" in item:
                image_ids.append(item["message_id"])
    return rep_id, image_ids


def _process_single_case(
    record: CaseRecord,
    config: Config,
    state: StateStore,
    telegram: TelegramClient,
    notion_client: NotionClient | None,
    database_id: str | None,
) -> None:
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

    rep_id, image_ids = send_case_to_telegram(telegram, config.telegram_auction_channel_id, record, text)
    message_link = private_channel_message_link(config.telegram_auction_channel_id, rep_id)

    sale_date = auction_info.sale_date
    case_state = CaseState(
        case_number=record.case_number,
        channel_id=config.telegram_auction_channel_id,
        representative_message_id=rep_id,
        image_message_ids=image_ids,
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

    if notion_client and database_id:
        try:
            notion_data = NotionCaseData(
                case_number=record.case_number,
                title=record.title,
                rating=record.rating or "$$$",
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
        except Exception:
            logger.exception("notion upsert failed for %s", record.case_number)

    state.upsert_case(case_state)
    state.save()


def process_pdf(
    pdf_path: Path,
    config: Config,
    state: StateStore,
    send: bool,
    tmp_root: Path,
) -> list[CaseProcessResult]:
    """PDF 하나를 분석하고, send=True면 실제 Telegram/Notion 반영까지 수행한다."""
    work_dir = tmp_root / f"work_{hash_file(pdf_path)[:12]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        records = analyze_pdf(pdf_path, work_dir, config.openai_api_key)
        results = dry_run_report(records)

        if not send:
            return results

        telegram = TelegramClient(config.telegram_auction_bot_token)
        notion_client = NotionClient(config.notion_token) if config.notion_token else None
        database_id = (
            extract_database_id(config.notion_auction_db_url)
            if notion_client and config.notion_auction_db_url
            else None
        )

        for record in filter_qualified_cases(records):
            try:
                _process_single_case(record, config, state, telegram, notion_client, database_id)
            except Exception:
                logger.exception("failed to process case %s", record.case_number)

        return results
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def poll_and_ingest(config: Config, state: StateStore) -> None:
    telegram = TelegramClient(config.telegram_auction_bot_token)
    tmp_root = config.tmp_dir
    tmp_root.mkdir(parents=True, exist_ok=True)

    updates = telegram.get_updates(offset=state.telegram_offset or None)
    for update in updates:
        update_id = update["update_id"]
        state.telegram_offset = update_id + 1
        try:
            _handle_update(update, config, state, telegram, tmp_root)
        except Exception:
            logger.exception("failed to handle update %s", update_id)
        state.save()


def _handle_update(
    update: dict, config: Config, state: StateStore, telegram: TelegramClient, tmp_root: Path
) -> None:
    message = update.get("message")
    if not message:
        return

    chat = message.get("chat", {})
    from_user = message.get("from", {})
    if chat.get("type") != "private":
        return
    allowed_id = config.telegram_allowed_user_id
    if not allowed_id or str(from_user.get("id")) != str(allowed_id):
        logger.info("ignoring message from unauthorized user")
        return

    document = message.get("document")
    if not document or document.get("mime_type") != "application/pdf":
        return

    chat_id = chat["id"]
    file_id = document["file_id"]
    file_size = document.get("file_size") or 0
    if file_size and file_size > MAX_PDF_BYTES:
        telegram.send_message(chat_id, "PDF 용량이 너무 큽니다 (20MB 제한). 더 작은 파일로 다시 보내주세요.")
        return

    pdf_path = tmp_root / f"in_{update['update_id']}.pdf"
    try:
        file_info = telegram.get_file(file_id)
        telegram.download_file(file_info["file_path"], pdf_path)
    except Exception:
        logger.exception("pdf download failed")
        telegram.send_message(chat_id, "PDF 다운로드에 실패했습니다. 잠시 후 다시 시도해주세요.")
        return

    try:
        pdf_hash = hash_file(pdf_path)
        if state.has_processed_pdf(pdf_hash):
            telegram.send_message(chat_id, "이미 처리된 PDF입니다 (중복).")
            return

        results = process_pdf(pdf_path, config, state, send=True, tmp_root=tmp_root)
        state.mark_pdf_processed(pdf_hash, {"file_name": document.get("file_name", "")})

        qualified = [r for r in results if r.processed]
        if qualified:
            summary = "\n".join(f"- {r.case_number} {r.rating} {r.title}" for r in qualified)
            telegram.send_message(chat_id, f"처리 완료: {len(qualified)}건\n{summary}")
        else:
            telegram.send_message(chat_id, "처리할 사건이 없습니다 ($$$ 이상 등급 없음).")
    except Exception:
        logger.exception("pdf processing failed")
        telegram.send_message(chat_id, "PDF 처리 중 오류가 발생했습니다.")
    finally:
        pdf_path.unlink(missing_ok=True)
