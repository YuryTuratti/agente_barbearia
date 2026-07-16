from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.models import InboundMessage, PendingSchedulingAction


@pytest.mark.anyio
async def test_pending_scheduling_action_persists_json_and_allows_one_active_action(db_session):
    inbound = InboundMessage(
        id="inbound-1",
        instance="turatti",
        message_id="message-1",
        phone="5534999999999",
        message_type="text",
        text="texto",
    )
    db_session.add(inbound)
    await db_session.commit()

    first = _action("action-1", "inbound-1")
    second = _action("action-2", "inbound-1")
    db_session.add(first)
    await db_session.commit()
    db_session.add(second)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    first.status = "superseded"
    db_session.add(second)
    await db_session.commit()

    actions = list((await db_session.execute(select(PendingSchedulingAction))).scalars().all())
    assert len(actions) == 2
    assert actions[1].payload["local_date"] == "2026-07-10"
    assert actions[1].confirmed_by_inbound_message_id is None


def test_pending_scheduling_action_migration_exists_and_downgrades() -> None:
    content = Path(
        "migrations/versions/202607050002_create_pending_scheduling_actions.py"
    ).read_text(encoding="utf-8")

    assert "pending_scheduling_actions" in content
    assert "uq_pending_scheduling_actions_active" in content
    assert "status = 'awaiting_confirmation'" in content
    assert "def downgrade" in content


def _action(action_id: str, inbound_id: str) -> PendingSchedulingAction:
    return PendingSchedulingAction(
        id=action_id,
        instance="turatti",
        phone="5534999999999",
        resource_key="main",
        action_type="create",
        status="awaiting_confirmation",
        payload={"local_date": "2026-07-10"},
        preview={"local_date": "2026-07-10"},
        confirmation_fingerprint="a" * 64,
        prepared_from_inbound_message_id=inbound_id,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
