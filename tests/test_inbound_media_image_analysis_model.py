import pytest
from sqlalchemy.exc import IntegrityError

from app.database.models import InboundMedia, InboundMessage


@pytest.mark.anyio
async def test_inbound_media_accepts_image_analysis_fields_and_nulls(db_session) -> None:
    message = InboundMessage(
        instance="turatti",
        message_id="IMAGE-MODEL",
        phone="5534999999999",
        message_type="image",
        status="pending",
        attempts=0,
    )
    db_session.add(message)
    await db_session.flush()
    media = InboundMedia(
        inbound_message_id=message.id,
        media_type="image",
        status="completed",
        attempts=1,
        source="inline_base64",
        media_locator={},
        analysis_kind="haircut_reference",
        analysis_data={"purpose": "haircut_reference"},
        extracted_text="Contexto visual controlado.",
    )
    db_session.add(media)
    await db_session.commit()

    assert media.analysis_kind == "haircut_reference"
    assert media.analysis_data == {"purpose": "haircut_reference"}


@pytest.mark.anyio
async def test_inbound_media_rejects_invalid_analysis_kind(db_session) -> None:
    message = InboundMessage(
        instance="turatti",
        message_id="IMAGE-MODEL-INVALID",
        phone="5534999999999",
        message_type="image",
        status="pending",
        attempts=0,
    )
    db_session.add(message)
    await db_session.flush()
    db_session.add(
        InboundMedia(
            inbound_message_id=message.id,
            media_type="image",
            status="completed",
            attempts=1,
            source="inline_base64",
            media_locator={},
            analysis_kind="face_identity",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()
