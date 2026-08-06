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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def cmd_validate_env(args: argparse.Namespace) -> int:
    result = validate_env()
    if result.ok:
        print("OK: 모든 필수 환경변수가 설정되어 있습니다.")
        return 0
    print("누락된 환경변수:")
    for name in result.missing:
        print(f"  - {name}")
    return 1


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
