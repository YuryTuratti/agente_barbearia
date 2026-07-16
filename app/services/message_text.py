from app.database.models import InboundMedia, InboundMessage


def get_effective_message_text(
    message: InboundMessage,
    media: InboundMedia | None = None,
) -> str | None:
    if (
        message.message_type == "image"
        and media is not None
        and media.status == "completed"
        and media.extracted_text
    ):
        return media.extracted_text
    if message.text is not None and message.text.strip():
        return message.text
    if media is not None and media.status == "completed" and media.extracted_text:
        return media.extracted_text
    return None


def get_confirmation_candidate_text(
    message: InboundMessage,
    media: InboundMedia | None = None,
) -> str | None:
    if message.message_type == "text":
        return message.text if message.text and message.text.strip() else None
    if (
        message.message_type == "audio"
        and media is not None
        and media.status == "completed"
        and media.extracted_text
    ):
        return media.extracted_text
    return None
