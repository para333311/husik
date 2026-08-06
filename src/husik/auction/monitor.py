"""경매마당/법원경매 adapter를 이용해 상태변경/낙찰결과를 감지하고 반영한다.

adapter 실패는 best-effort로 흡수하며, 실패해도 전체 auction-monitor 플로우는 멈추지 않는다.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from husik.auction.adapters import AuctionInfo, safe_fetch
from husik.auction.court import CourtAuctionAdapter
from husik.auction.madangs import MadangsAdapter
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
    build_award_update,
    build_event_update,
)

logger = logging.getLogger(__name__)


def enrich_case(case_number: str, config: Config) -> AuctionInfo:
    info = AuctionInfo(court="확인중", address="확인중", status="확인중")
    if config.court_auction_enabled:
        info = info.merge(safe_fetch(CourtAuctionAdapter(), case_number))
    if config.madangs_enabled:
        info = info.merge(safe_fetch(MadangsAdapter(), case_number))
    return info


def has_new_award_result(previous: dict, current: AuctionInfo) -> bool:
    return current.winning_price is not None and not previous.get("winning_price")


def has_status_change(previous: dict, current: AuctionInfo) -> bool:
    prev_status = previous.get("status")
    return bool(current.status) and current.status not in (None, "확인중") and current.status != prev_status


def _serialize(info: AuctionInfo) -> dict:
    data = asdict(info)
    if data.get("sale_date"):
        data["sale_date"] = data["sale_date"].isoformat()
    return data


def run_auction_monitor(config: Config, state: StateStore) -> None:
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
            _monitor_case_auction(case, config, state, telegram, notion_client, database_id)
        except Exception:
            logger.exception("auction monitor failed for case %s", case.case_number)

    state.save()


def _monitor_case_auction(
    case: CaseState,
    config: Config,
    state: StateStore,
    telegram: TelegramClient | None,
    notion_client: NotionClient | None,
    database_id: str | None,
) -> None:
    previous = case.auction_info or {}
    current = enrich_case(case.case_number, config)

    award_new = has_new_award_result(previous, current)
    status_changed = has_status_change(previous, current)

    if not award_new and not status_changed:
        merged = dict(previous)
        merged.update({k: v for k, v in _serialize(current).items() if v is not None})
        case.auction_info = merged
        state.upsert_case(case)
        return

    auction = AuctionFields(
        court=current.court or previous.get("court") or "확인중",
        address=current.address or previous.get("address") or "확인중",
        appraisal_price=current.appraisal_price
        if current.appraisal_price is not None
        else previous.get("appraisal_price"),
        min_price=current.min_price if current.min_price is not None else previous.get("min_price"),
        sale_date=current.sale_date,
        status=current.status or "확인중",
        winning_price=current.winning_price,
        winning_rate=current.winning_rate,
        bidder_count=current.bidder_count,
        madangs_link=current.madangs_link or previous.get("madangs_link") or "확인중",
        court_link=current.court_link or previous.get("court_link") or "확인중",
    )
    message_data = CaseMessageData(
        case_number=case.case_number,
        rating=case.rating or "$$$",
        title=case.title,
        auction=auction,
        interest=InterestStats(
            court_views=current.court_views,
            madangs_views=current.madangs_views,
            blog_mentions=len(case.blog_urls),
            recent_blog_mentions=0,
        ),
        image_count=len(case.image_message_ids),
    )

    if telegram and case.representative_message_id and case.channel_id:
        try:
            if award_new:
                updated_text = build_award_update(message_data, existing_message="낙찰결과 반영 전 상태")
            else:
                prev_status = previous.get("status", "확인중")
                note = f"상태: {prev_status} -> {current.status}"
                updated_text = build_event_update("상태변경", message_data, existing_message=note)
            telegram.edit_message_text(case.channel_id, case.representative_message_id, updated_text)
        except Exception:
            logger.exception("failed to edit telegram message for %s", case.case_number)

    case.status = current.status or case.status
    case.auction_info = _serialize(current)

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
                court=auction.court,
                address=auction.address,
                appraisal_price=auction.appraisal_price,
                min_price=auction.min_price,
                sale_date=auction.sale_date,
                status=auction.status,
                winning_price=auction.winning_price,
                winning_rate=auction.winning_rate,
                bidder_count=auction.bidder_count,
                court_views=current.court_views,
                madangs_views=current.madangs_views,
                blog_mentions=len(case.blog_urls),
                recent_blog_mentions=0,
                madangs_link=auction.madangs_link,
                court_link=auction.court_link,
                telegram_message_link=message_link,
            )
            tag = "낙찰결과" if award_new else "상태변경"
            page_id = upsert_case_page(
                notion_client, database_id, notion_data, log_lines=[f"[{tag}] {current.status}"]
            )
            case.notion_page_id = page_id
        except Exception:
            logger.exception("notion update failed for %s", case.case_number)

    state.upsert_case(case)
