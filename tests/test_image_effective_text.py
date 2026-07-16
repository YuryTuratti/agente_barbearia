from app.database.models import InboundMedia, InboundMessage
from app.services.message_text import get_effective_message_text


def test_effective_text_uses_controlled_image_context_before_caption() -> None:
    image = InboundMessage(
        instance="turatti",
        message_id="IMAGE-EFFECTIVE",
        phone="5534999999999",
        message_type="image",
        text="Quero parecido",
        status="completed",
        attempts=1,
    )
    media = InboundMedia(
        inbound_message_id="image-id",
        media_type="image",
        status="completed",
        attempts=1,
        source="inline_base64",
        media_locator={},
        extracted_text="Mensagem escrita pelo cliente: Quero parecido\n\nContexto visual controlado.",
    )

    assert get_effective_message_text(image, media) == media.extracted_text


def test_effective_text_keeps_text_and_audio_behaviour() -> None:
    text = InboundMessage(
        instance="turatti",
        message_id="TEXT-EFFECTIVE",
        phone="5534999999999",
        message_type="text",
        text="Ola",
        status="completed",
        attempts=1,
    )
    audio = InboundMessage(
        instance="turatti",
        message_id="AUDIO-EFFECTIVE",
        phone="5534999999999",
        message_type="audio",
        text=None,
        status="completed",
        attempts=1,
    )
    audio_media = InboundMedia(
        inbound_message_id="audio-id",
        media_type="audio",
        status="completed",
        attempts=1,
        source="inline_base64",
        media_locator={},
        extracted_text="Audio transcrito",
    )

    assert get_effective_message_text(text) == "Ola"
    assert get_effective_message_text(audio, audio_media) == "Audio transcrito"
