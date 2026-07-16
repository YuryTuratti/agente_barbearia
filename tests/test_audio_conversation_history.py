from datetime import UTC, datetime, timedelta

import pytest

from app.database.models import InboundMedia, InboundMessage
from app.repositories.conversation_history_repository import get_recent_conversation


@pytest.mark.anyio
async def test_completed_audio_transcription_enters_conversation_history(db_session) -> None:
    now = datetime.now(UTC)
    text = InboundMessage(
        instance="turatti",
        message_id="TEXT1",
        phone="5534999999999",
        message_type="text",
        text="Mensagem escrita",
        status="completed",
        attempts=1,
        created_at=now - timedelta(minutes=3),
    )
    audio = InboundMessage(
        instance="turatti",
        message_id="AUDIO-HISTORY",
        phone="5534999999999",
        message_type="audio",
        text=None,
        status="completed",
        attempts=1,
        created_at=now - timedelta(minutes=2),
    )
    failed_audio = InboundMessage(
        instance="turatti",
        message_id="AUDIO-FAILED",
        phone="5534999999999",
        message_type="audio",
        text=None,
        status="completed",
        attempts=1,
        created_at=now - timedelta(minutes=1),
    )
    db_session.add_all([text, audio, failed_audio])
    await db_session.flush()
    db_session.add_all(
        [
            InboundMedia(
                inbound_message_id=audio.id,
                media_type="audio",
                mimetype="audio/ogg",
                status="completed",
                attempts=1,
                source="inline_base64",
                media_locator={"message_id": "AUDIO-HISTORY"},
                inline_base64=None,
                extracted_text="Audio transcrito",
            ),
            InboundMedia(
                inbound_message_id=failed_audio.id,
                media_type="audio",
                mimetype="audio/ogg",
                status="failed",
                attempts=1,
                source="inline_base64",
                media_locator={"message_id": "AUDIO-FAILED"},
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

    assert [(item.role, item.content) for item in history] == [
        ("user", "Mensagem escrita"),
        ("user", "Audio transcrito"),
    ]
    assert all("base64" not in item.content for item in history)
    assert all("audio/ogg" not in item.content for item in history)
