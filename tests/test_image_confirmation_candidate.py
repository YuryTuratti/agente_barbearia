from app.database.models import InboundMedia, InboundMessage
from app.services.message_text import get_confirmation_candidate_text


def test_confirmation_candidate_text_accepts_text_and_audio_but_not_image() -> None:
    text = InboundMessage(
        instance="turatti",
        message_id="TEXT-CONFIRM",
        phone="5534999999999",
        message_type="text",
        text="sim",
        status="pending",
        attempts=0,
    )
    audio = InboundMessage(
        instance="turatti",
        message_id="AUDIO-CONFIRM",
        phone="5534999999999",
        message_type="audio",
        text=None,
        status="pending",
        attempts=0,
    )
    audio_media = InboundMedia(
        inbound_message_id="audio-id",
        media_type="audio",
        status="completed",
        attempts=1,
        source="inline_base64",
        media_locator={},
        extracted_text="confirmo",
    )
    image = InboundMessage(
        instance="turatti",
        message_id="IMAGE-CONFIRM",
        phone="5534999999999",
        message_type="image",
        text="sim",
        status="pending",
        attempts=0,
    )
    image_media = InboundMedia(
        inbound_message_id="image-id",
        media_type="image",
        status="completed",
        attempts=1,
        source="inline_base64",
        media_locator={},
        extracted_text="Mensagem escrita pelo cliente: sim",
    )

    assert get_confirmation_candidate_text(text) == "sim"
    assert get_confirmation_candidate_text(audio, audio_media) == "confirmo"
    assert get_confirmation_candidate_text(image, image_media) is None
