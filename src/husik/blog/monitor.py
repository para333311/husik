"""사건별 블로그 신규 언급 모니터링 (관심도 점수화 없이 숫자만 표시)."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from husik.blog.naver import BlogPost, search_blog
from husik.config import Config
from husik.notion.client import NotionClient, extract_database_id
from husik.notion.upsert import NotionCaseData, upsert_case_page
from husik.state.store import CaseState, StateStore
from husik.telegram.client import TelegramClient
from husik.telegram.links import private_channel_message_link
from husik.telegram.templates import (
    AuctionFields,
    CaseMessageData,
    InterestStats,
    auction_fields_from_dict,
    build_event_update,
)

logger = logging.getLogger(__name__)

CASE_SPACED_RE = re.compile(r"(\d{4})타경(\d+)")


def build_keywords(case_number: str, title: str, address: str) -> list[str]:
    match = CASE_SPACED_RE.match(case_number)
    spaced = f"{match.group(1)} 타경 {match.group(2)}" if match else case_number

    keywords = [case_number, spaced]
    if title and title != case_number:
        keywords.append(f"{title} {case_number}")
    if address:
        keywords.append(f"{address} {case_number}")

    seen: list[str] = []
    for k in keywords:
        if k not in seen:
            seen.append(k)
    return seen


def find_new_posts(
    client_id: str,
    client_secret: str,
    case_number: str,
    title: str,
    address: str,
    known_urls: set[str],
) -> list[BlogPost]:
    found: dict[str, BlogPost] = {}
    for keyword in build_keywords(case_number, title, address):
        for post in search_blog(client_id, client_secret, keyword):
            if post.link not in known_urls and post.link not in found:
                found[post.link] = post
    return list(found.values())


def is_within_days(post_date: str, days: int, today: date | None = None) -> bool:
    today = today or date.today()
    try:
        parsed = datetime.strptime(post_date, "%Y%m%d").date()
    except ValueError:
        return False
    return 0 <= (today - parsed).days <= days


def run_blog_monitor(config: Config, state: StateStore) -> None:
    if not config.blog_monitor_enabled:
        logger.info("blog monitor disabled by BLOG_MONITOR_ENABLED")
        return

    telegram = (
        TelegramClient(config.telegram_auction_bot_token) if config.telegram_auction_bot_token else None
    )
    notion_client = NotionClient(config.notion_token) if config.notion_token else None
    database_id = (
        extract_database_id(config.notion_auction_db_url)
        if notion_client and config.notion_auction_db_url
        else None
    )

    for case in state.all_cases():
        try:
            _monitor_single_case(case, config, state, telegram, notion_client, database_id)
        except Exception:
            logger.exception("blog monitor failed for case %s", case.case_number)

    state.save()


def _monitor_single_case(
    case: CaseState,
    config: Config,
    state: StateStore,
    telegram: TelegramClient | None,
    notion_client: NotionClient | None,
    database_id: str | None,
) -> None:
    address = case.auction_info.get("address") or ""
    known = set(case.blog_urls)
    new_posts = find_new_posts(
        config.naver_client_id, config.naver_client_secret, case.case_number, case.title, address, known
    )
    if not new_posts:
        return

    case.blog_urls = list(known) + [p.link for p in new_posts]
    recent = sum(1 for p in new_posts if is_within_days(p.post_date, 7))
    auction_fields: AuctionFields = auction_fields_from_dict(case.auction_info)

    message_data = CaseMessageData(
        case_number=case.case_number,
        rating=case.rating or "$$$",
        title=case.title,
        auction=auction_fields,
        interest=InterestStats(
            court_views=case.auction_info.get("court_views"),
            madangs_views=case.auction_info.get("madangs_views"),
            blog_mentions=len(case.blog_urls),
            recent_blog_mentions=recent,
        ),
        image_count=len(case.image_message_ids),
    )

    if telegram and case.representative_message_id and case.channel_id:
        try:
            new_links_text = "\n".join(f"- {p.link}" for p in new_posts)
            existing_note = f"신규 블로그 {len(new_posts)}건 발견\n{new_links_text}"
            updated_text = build_event_update("블로그업데이트", message_data, existing_message=existing_note)
            telegram.edit_message_text(case.channel_id, case.representative_message_id, updated_text)
        except Exception:
            logger.exception("failed to edit telegram message for %s", case.case_number)

    if notion_client and database_id:
        try:
            message_link = (
                private_channel_message_link(case.channel_id, case.representative_message_id)
                if case.representative_message_id
                else ""
            )
            notion_data = NotionCaseData(
                case_number=case.case_number,
                title=case.title,
                rating=case.rating or "$$$",
                item_number="확인중",
                court=auction_fields.court,
                address=auction_fields.address,
                appraisal_price=auction_fields.appraisal_price,
                min_price=auction_fields.min_price,
                sale_date=auction_fields.sale_date,
                status=auction_fields.status,
                winning_price=auction_fields.winning_price,
                winning_rate=auction_fields.winning_rate,
                bidder_count=auction_fields.bidder_count,
                court_views=case.auction_info.get("court_views"),
                madangs_views=case.auction_info.get("madangs_views"),
                blog_mentions=len(case.blog_urls),
                recent_blog_mentions=recent,
                madangs_link=auction_fields.madangs_link,
                court_link=auction_fields.court_link,
                telegram_message_link=message_link,
            )
            new_links = "\n".join(f"- {p.title}: {p.link}" for p in new_posts)
            page_id = upsert_case_page(
                notion_client,
                database_id,
                notion_data,
                log_lines=[f"[블로그업데이트] 신규 {len(new_posts)}건", new_links],
            )
            case.notion_page_id = page_id
        except Exception:
            logger.exception("notion update failed for %s", case.case_number)

    state.upsert_case(case)
