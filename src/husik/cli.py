"""husik CLI 엔트리포인트.

python -m husik.cli <command> 형태로 실행한다.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from husik.config import load_config, validate_env
from husik.state.store import StateStore
from husik.telegram.channel import validate_channel_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def cmd_validate_env(args: argparse.Namespace) -> int:
    result = validate_env()
    if not result.ok:
        print("누락된 환경변수:")
        for name in result.missing:
            print(f"  - {name}")
        return 1

    print("OK: 모든 필수 환경변수가 설정되어 있습니다.")

    config = load_config()
    valid, reason = validate_channel_id(config.telegram_auction_channel_id)
    if valid:
        print(f"OK: TELEGRAM_AUCTION_CHANNEL_ID 형식 확인됨 ({reason})")
    else:
        print(f"경고: TELEGRAM_AUCTION_CHANNEL_ID 형식을 확인하세요 - {reason}")
    return 0


def cmd_telegram_pdf_ingest(args: argparse.Namespace) -> int:
    from husik.telegram.ingest import poll_and_ingest

    config = load_config()
    state = StateStore(config.state_dir)
    poll_and_ingest(config, state)
    return 0


def cmd_process_local_pdf(args: argparse.Namespace) -> int:
    from husik.telegram.ingest import process_pdf

    config = load_config()
    state = StateStore(config.state_dir)
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"파일을 찾을 수 없습니다: {pdf_path}", file=sys.stderr)
        return 1

    tmp_root = config.tmp_dir
    tmp_root.mkdir(parents=True, exist_ok=True)
    results = process_pdf(pdf_path, config, state, send=args.send, tmp_root=tmp_root)

    print(f"{'사건번호':<16}{'달러등급':<10}{'제목':<30}{'페이지범위':<12}{'처리 여부'}")
    for r in results:
        status = "처리" if r.processed else (f"버림({r.reason})" if r.reason else "버림")
        page_range = f"{r.page_start}-{r.page_end}p"
        print(f"{r.case_number:<16}{r.rating:<10}{r.title[:28]:<30}{page_range:<12}{status}")
    return 0


def cmd_telegram_diagnose(args: argparse.Namespace) -> int:
    """토큰 값 자체는 절대 출력하지 않고, getMe/webhook/채널 접근 여부만 진단한다."""
    from husik.telegram.channel import diagnose_channel_access
    from husik.telegram.client import TelegramClient, TelegramError

    config = load_config()
    print("=== Telegram 진단 ===")

    if not config.telegram_auction_bot_token:
        print("[FAIL] TELEGRAM_AUCTION_BOT_TOKEN이 설정되어 있지 않습니다.")
        return 1

    telegram = TelegramClient(config.telegram_auction_bot_token)

    try:
        me = telegram.get_me()
        print(f"[OK] getMe 성공 (username=@{me.get('username', '?')})")
    except TelegramError as exc:
        print(f"[FAIL] getMe 실패: {exc}")
        return 1

    try:
        info = telegram.get_webhook_info()
        had_webhook = bool(info.get("url"))
        telegram.delete_webhook(drop_pending_updates=False)
        print(f"[OK] webhook {'삭제됨 (기존에 설정되어 있었음)' if had_webhook else '없음 (정상)'}")
    except TelegramError as exc:
        print(f"[WARN] webhook 확인/삭제 실패: {exc}")

    valid, reason = validate_channel_id(config.telegram_auction_channel_id)
    print(f"[{'OK' if valid else 'FAIL'}] TELEGRAM_AUCTION_CHANNEL_ID 형식: {reason}")

    if valid:
        diag = diagnose_channel_access(telegram, config.telegram_auction_channel_id)
        if diag.chat_ok:
            print(f"[OK] 출력 채널 접근 가능 (title={diag.chat_title or '확인불가'})")
        else:
            print(f"[FAIL] 출력 채널 접근 불가: {diag.error}")
        if diag.send_ok:
            if diag.delete_ok:
                note = "테스트 메시지 삭제됨"
            else:
                note = "삭제 권한이 없어 [시스템테스트] 메시지가 채널에 남아있을 수 있음"
            print(f"[OK] 출력 채널 테스트 메시지 전송 성공 ({note})")
        elif diag.chat_ok:
            print(f"[FAIL] 출력 채널 테스트 메시지 전송 실패: {diag.error}")

    print("=== 진단 종료 (토큰 값은 출력하지 않았습니다) ===")
    return 0


def cmd_telegram_updates_dry_run(args: argparse.Namespace) -> int:
    from husik.telegram.client import TelegramClient

    config = load_config()
    state = StateStore(config.state_dir)
    telegram = TelegramClient(config.telegram_auction_bot_token)

    try:
        telegram.delete_webhook(drop_pending_updates=False)
    except Exception:
        logger.warning("webhook 삭제 실패 (계속 진행)")

    updates = telegram.get_updates(
        offset=state.telegram_offset or None, allowed_updates=["message", "channel_post"]
    )

    messages = 0
    documents = 0
    pdf_documents = 0
    channel_posts = 0
    max_update_id: int | None = None
    for u in updates:
        if u.get("channel_post") is not None:
            channel_posts += 1
        msg = u.get("message")
        if msg:
            messages += 1
            document = msg.get("document")
            if document:
                documents += 1
                if document.get("mime_type") == "application/pdf":
                    pdf_documents += 1
        if max_update_id is None or u["update_id"] > max_update_id:
            max_update_id = u["update_id"]

    print(f"updates={len(updates)}")
    print(f"messages={messages}")
    print(f"channel_posts={channel_posts}")
    print(f"documents={documents}")
    print(f"pdf_documents={pdf_documents}")

    if args.commit_offset and max_update_id is not None:
        state.telegram_offset = max_update_id + 1
        state.save()
        print(f"offset committed -> {state.telegram_offset}")
    else:
        print("offset 변경 없음 (--commit-offset 미지정)")
    return 0


def cmd_blog_monitor(args: argparse.Namespace) -> int:
    from husik.blog.monitor import run_blog_monitor

    config = load_config()
    state = StateStore(config.state_dir)
    run_blog_monitor(config, state)
    return 0


def cmd_auction_monitor(args: argparse.Namespace) -> int:
    from husik.auction.monitor import run_auction_monitor

    config = load_config()
    state = StateStore(config.state_dir)
    run_auction_monitor(config, state)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="husik", description="매수맛집 경매 자동복기 시스템")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate-env", help="필수 환경변수 검증").set_defaults(func=cmd_validate_env)

    sub.add_parser("telegram-pdf-ingest", help="Telegram PDF polling ingest").set_defaults(
        func=cmd_telegram_pdf_ingest
    )

    sub.add_parser(
        "telegram-diagnose", help="봇 토큰/webhook/출력 채널 접근 여부 진단 (토큰 값은 출력하지 않음)"
    ).set_defaults(func=cmd_telegram_diagnose)

    p_dry = sub.add_parser(
        "telegram-updates-dry-run", help="getUpdates 조회만 하고 처리/전송은 하지 않음"
    )
    p_dry.add_argument(
        "--commit-offset", action="store_true", help="지정하면 조회한 최신 update까지 offset을 저장"
    )
    p_dry.set_defaults(func=cmd_telegram_updates_dry_run)

    p = sub.add_parser("process-local-pdf", help="로컬 PDF 처리 (테스트용)")
    p.add_argument("pdf_path")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", dest="dry_run", help="전송 없이 감지 결과만 출력")
    group.add_argument("--send", action="store_true", dest="send", help="Telegram/Notion에 실제 전송")
    p.set_defaults(func=cmd_process_local_pdf, send=False)

    sub.add_parser("blog-monitor", help="일일 블로그 모니터링").set_defaults(func=cmd_blog_monitor)
    sub.add_parser(
        "auction-monitor", help="일일 경매 상태/낙찰결과 모니터링"
    ).set_defaults(func=cmd_auction_monitor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
