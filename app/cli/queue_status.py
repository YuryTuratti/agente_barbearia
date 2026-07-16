import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.database.connection import AsyncSessionLocal, engine
from app.database.models import InboundMedia, InboundMessage, OutboundMessage, PendingSchedulingAction

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show queue status without PII.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


async def collect_queue_status(settings: Settings | None = None) -> dict[str, Any]:
    active_settings = settings or get_settings()
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        inbound = await _queue_summary(
            session,
            model=InboundMessage,
            statuses=["pending", "processing", "completed", "failed"],
            stuck_status="processing",
            stuck_before=now - timedelta(seconds=active_settings.worker_processing_timeout_seconds),
        )
        outbound = await _queue_summary(
            session,
            model=OutboundMessage,
            statuses=["pending", "sending", "sent", "failed"],
            stuck_status="sending",
            stuck_before=now - timedelta(seconds=active_settings.outbound_worker_processing_timeout_seconds),
        )
        media = await _queue_summary(
            session,
            model=InboundMedia,
            statuses=["pending", "processing", "completed", "failed", "unsupported"],
            stuck_status="processing",
            stuck_before=now - timedelta(seconds=active_settings.media_processing_timeout_seconds),
        )
        actions = await _action_summary(session)
    return {
        "inbound": inbound,
        "outbound": outbound,
        "media": media,
        "scheduling_actions": actions,
    }


async def _queue_summary(session, *, model, statuses: list[str], stuck_status: str, stuck_before: datetime) -> dict[str, Any]:
    counts = {status: 0 for status in statuses}
    result = await session.execute(
        select(model.status, func.count()).group_by(model.status)
    )
    for status, count in result.all():
        if status in counts:
            counts[status] = count
    stuck_result = await session.execute(
        select(func.count())
        .select_from(model)
        .where(model.status == stuck_status, model.locked_at.is_not(None), model.locked_at < stuck_before)
    )
    oldest_pending_result = await session.execute(
        select(func.min(model.created_at)).where(model.status == "pending")
    )
    failed_24h_result = await session.execute(
        select(func.count())
        .select_from(model)
        .where(model.status == "failed", model.updated_at >= datetime.now(UTC) - timedelta(hours=24))
    )
    oldest_pending = oldest_pending_result.scalar_one_or_none()
    return {
        "counts": counts,
        "stuck_items": stuck_result.scalar_one(),
        "oldest_pending_at": oldest_pending.isoformat() if oldest_pending else None,
        "failed_last_24h": failed_24h_result.scalar_one(),
    }


async def _action_summary(session) -> dict[str, Any]:
    result = await session.execute(
        select(PendingSchedulingAction.status, func.count()).group_by(PendingSchedulingAction.status)
    )
    counts = {status: count for status, count in result.all()}
    oldest_result = await session.execute(
        select(func.min(PendingSchedulingAction.created_at)).where(
            PendingSchedulingAction.status == "awaiting_confirmation"
        )
    )
    failed_24h_result = await session.execute(
        select(func.count())
        .select_from(PendingSchedulingAction)
        .where(
            PendingSchedulingAction.status == "failed",
            PendingSchedulingAction.updated_at >= datetime.now(UTC) - timedelta(hours=24),
        )
    )
    oldest_pending = oldest_result.scalar_one_or_none()
    return {
        "counts": counts,
        "stuck_items": counts.get("executing", 0),
        "oldest_pending_at": oldest_pending.isoformat() if oldest_pending else None,
        "failed_last_24h": failed_24h_result.scalar_one(),
    }


def format_text(status: dict[str, Any]) -> str:
    lines = ["Queue status"]
    for section_name in ("inbound", "outbound", "media", "scheduling_actions"):
        section = status[section_name]
        lines.append(f"{section_name}:")
        for key, value in section["counts"].items():
            lines.append(f"  {key}: {value}")
        lines.append(f"  stuck_items: {section['stuck_items']}")
        lines.append(f"  oldest_pending_at: {section['oldest_pending_at'] or '-'}")
        lines.append(f"  failed_last_24h: {section['failed_last_24h']}")
    return "\n".join(lines)


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings)
    try:
        status = await collect_queue_status(settings)
    except Exception as error:
        logger.error("Queue status failed: error_type=%s", error.__class__.__name__)
        return 1
    finally:
        await engine.dispose()
    if args.json:
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
    else:
        print(format_text(status))
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
