from datetime import UTC, datetime, timedelta

import pytest

from app.database.models import InboundMedia, InboundMessage
from app.repositories.conversation_history_repository import get_recent_conversation


@pytest.mark.anyio
async def test_completed_image_analysis_enters_conversation_history(db_session) -> None:
    now = datetime.now(UTC)
    image = InboundMessage(
        instance="turatti",
        message_id="IMAGE-HISTORY",
        phone="5534999999999",
        message_type="image",
        text="Legenda",
        status="completed",
        attempts=1,
        created_at=now - timedelta(minutes=2),
    )
    failed = InboundMessage(
        instance="turatti",
        message_id="IMAGE-FAILED-HISTORY",
        phone="5534999999999",
        message_type="image",
        text=None,
        status="completed",
        attempts=1,
        created_at=now - timedelta(minutes=1),
    )
    db_session.add_all([image, failed])
    await db_session.flush()
    db_session.add_all(
        [
            InboundMedia(
                inbound_message_id=image.id,
                media_type="image",
                mimetype="image/jpeg",
                status="completed",
                attempts=1,
                source="inline_base64",
                media_locator={},
                inline_base64=None,
                extracted_text="Mensagem escrita pelo cliente: Legenda\n\nContexto visual controlado.",
                analysis_kind="haircut_reference",
                analysis_data={"purpose": "haircut_reference"},
            ),
            InboundMedia(
                inbound_message_id=failed.id,
                media_type="image",
                mimetype="image/jpeg",
                status="failed",
                attempts=1,
                source="inline_base64",
                media_locator={},
                inline_base64="base64",
                extracted_text=None,
            ),
        ]
    )
    await db_session.commit()

    history = await get_recent_conversation(
        db_session,
        instance="turatti",
        phone="5534999999999",
        current_inbound_message_id="CURRENT",
        limit=10,
    )

    assert len(history) == 1
    assert history[0].role == "user"
    assert "Contexto visual controlado" in history[0].content
    assert "base64" not in history[0].content
    assert "analysis_data" not in history[0].content
    assert "haircut_reference" not in history[0].content
