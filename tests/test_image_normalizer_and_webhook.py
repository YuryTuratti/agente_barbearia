import base64

import anyio
from sqlalchemy import select

from app.database.models import InboundMedia
from app.services.message_normalizer import normalize_evolution_message


def test_normalizer_extracts_image_media_descriptor_without_decoding() -> None:
    payload = _image_payload(base64.b64encode(b"image").decode())

    message = normalize_evolution_message(payload)

    assert message.message_type == "image"
    assert message.text == "Quero parecido"
    assert message.media is not None
    assert message.media.media_type == "image"
    assert message.media.mimetype == "image/jpeg; charset=binary"
    assert message.media.file_name == "referencia.jpg"
    assert message.media.file_size_bytes == 5
    assert message.media.inline_base64 is not None
    assert message.media.locator["message_id"] == "IMAGE1"


def test_normalizer_image_without_mimetype_does_not_break() -> None:
    payload = _image_payload(None)
    image = payload["data"]["message"]["imageMessage"]
    del image["mimetype"]

    message = normalize_evolution_message(payload)

    assert message.media is not None
    assert message.media.mimetype is None


def test_webhook_image_creates_inbound_media_without_analysis(client, session_maker) -> None:
    response = client.post(
        "/webhooks/evolution",
        json=_image_payload(base64.b64encode(b"image").decode()),
    )

    assert response.status_code == 200
    assert "base64" not in response.text
    assert "locator" not in response.text
    async def inspect():
        async with session_maker() as session:
            return list((await session.execute(select(InboundMedia))).scalars().all())

    media = anyio.run(inspect)
    assert len(media) == 1
    assert media[0].media_type == "image"
    assert media[0].status == "pending"
    assert media[0].analysis_kind is None


def test_webhook_image_duplicate_does_not_create_second_media(client, session_maker) -> None:
    payload = _image_payload(base64.b64encode(b"image").decode())
    assert client.post("/webhooks/evolution", json=payload).status_code == 200
    assert client.post("/webhooks/evolution", json=payload).status_code == 200

    async def inspect():
        async with session_maker() as session:
            return list((await session.execute(select(InboundMedia))).scalars().all())

    assert len(anyio.run(inspect)) == 1


def _image_payload(inline_base64: str | None) -> dict[str, object]:
    image = {
        "mimetype": "image/jpeg; charset=binary",
        "fileName": "referencia.jpg",
        "fileLength": "5",
        "caption": "Quero parecido",
    }
    if inline_base64 is not None:
        image["base64"] = inline_base64
    return {
        "event": "messages.upsert",
        "instance": "turatti",
        "data": {
            "key": {
                "id": "IMAGE1",
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "Cliente",
            "messageTimestamp": 1,
            "message": {"imageMessage": image},
        },
    }
