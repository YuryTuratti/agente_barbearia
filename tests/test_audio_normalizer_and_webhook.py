import base64

from sqlalchemy import select

from app.database.models import InboundMedia
from app.services.message_normalizer import normalize_evolution_message


def test_normalizer_extracts_audio_media_descriptor_without_decoding() -> None:
    payload = _audio_payload(base64.b64encode(b"audio").decode())

    message = normalize_evolution_message(payload)

    assert message.message_type == "audio"
    assert message.media is not None
    assert message.media.media_type == "audio"
    assert message.media.mimetype == "audio/ogg; codecs=opus"
    assert message.media.file_size_bytes == 5
    assert message.media.inline_base64 is not None
    assert message.media.locator["message_id"] == "AUDIO1"
    assert message.phone == "5534999999999"


def test_normalizer_does_not_break_without_audio_base64() -> None:
    payload = _audio_payload(None)

    message = normalize_evolution_message(payload)

    assert message.media is not None
    assert message.media.inline_base64 is None


def test_webhook_audio_creates_inbound_media_without_downloading(client, session_maker) -> None:
    response = client.post("/webhooks/evolution", json=_audio_payload(base64.b64encode(b"audio").decode()))

    assert response.status_code == 200
    assert "base64" not in response.text
    async def inspect():
        async with session_maker() as session:
            return list((await session.execute(select(InboundMedia))).scalars().all())
    import anyio

    media = anyio.run(inspect)
    assert len(media) == 1
    assert media[0].status == "pending"
    assert media[0].inline_base64 is not None


def test_webhook_audio_duplicate_does_not_create_second_media(client, session_maker) -> None:
    payload = _audio_payload(base64.b64encode(b"audio").decode())
    assert client.post("/webhooks/evolution", json=payload).status_code == 200
    assert client.post("/webhooks/evolution", json=payload).status_code == 200

    async def inspect():
        async with session_maker() as session:
            return list((await session.execute(select(InboundMedia))).scalars().all())
    import anyio

    assert len(anyio.run(inspect)) == 1


def _audio_payload(inline_base64: str | None) -> dict[str, object]:
    audio = {
        "mimetype": "audio/ogg; codecs=opus",
        "fileLength": "5",
    }
    if inline_base64 is not None:
        audio["base64"] = inline_base64
    return {
        "event": "messages.upsert",
        "instance": "turatti",
        "data": {
            "key": {
                "id": "AUDIO1",
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "Cliente",
            "messageTimestamp": 1,
            "message": {"audioMessage": audio},
        },
    }
