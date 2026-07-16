import re
from collections.abc import Mapping

from app.schemas.normalized_message import MessageType, NormalizedMedia, NormalizedMessage

PROCESSABLE_MESSAGE_TYPES: set[MessageType] = {
    "text",
    "audio",
    "image",
    "video",
    "document",
}


def normalize_evolution_message(
    payload: dict[str, object],
) -> NormalizedMessage:
    """Normalize an Evolution API webhook payload into a stable message shape."""
    data = _get_mapping(payload, "data")
    key = _get_mapping(data, "key")
    message = _get_mapping(data, "message")

    event = _get_str(payload, "event")
    instance = _get_str(payload, "instance")
    remote_jid = _get_str(key, "remoteJid")
    message_type = _detect_message_type(message)
    text = _extract_text(message, message_type)
    from_me = _get_bool(key, "fromMe")
    is_group = _is_group_jid(remote_jid)

    normalized = NormalizedMessage(
        event=event,
        instance=instance,
        message_id=_get_str(key, "id"),
        remote_jid=remote_jid,
        phone=_extract_phone(remote_jid, is_group),
        sender_name=_get_str(data, "pushName"),
        from_me=from_me,
        is_group=is_group,
        message_type=message_type,
        text=text,
        media_mimetype=_extract_media_mimetype(message, message_type),
        media=_extract_media(message, message_type, key),
        timestamp=_extract_timestamp(data),
    )

    ignore_reason = _get_ignore_reason(normalized)
    normalized.processable = ignore_reason is None
    normalized.ignore_reason = ignore_reason

    return normalized


def _get_mapping(
    source: Mapping[str, object] | None,
    key: str,
) -> Mapping[str, object]:
    if source is None:
        return {}

    value = source.get(key)
    if isinstance(value, Mapping):
        return value

    return {}


def _get_str(source: Mapping[str, object], key: str) -> str | None:
    value = source.get(key)
    if isinstance(value, str):
        return value

    return None


def _get_bool(source: Mapping[str, object], key: str) -> bool:
    return source.get(key) is True


def _detect_message_type(message: Mapping[str, object]) -> MessageType:
    if "conversation" in message or "extendedTextMessage" in message:
        return "text"
    if "audioMessage" in message:
        return "audio"
    if "imageMessage" in message:
        return "image"
    if "videoMessage" in message:
        return "video"
    if "documentMessage" in message or "documentWithCaptionMessage" in message:
        return "document"
    if "stickerMessage" in message:
        return "sticker"

    return "unknown"


def _extract_text(
    message: Mapping[str, object],
    message_type: MessageType,
) -> str | None:
    if message_type == "text":
        conversation = _get_str(message, "conversation")
        if conversation is not None:
            return conversation

        extended_text = _get_mapping(message, "extendedTextMessage")
        return _get_str(extended_text, "text")

    if message_type == "image":
        image_message = _get_mapping(message, "imageMessage")
        return _get_str(image_message, "caption")

    if message_type == "video":
        video_message = _get_mapping(message, "videoMessage")
        return _get_str(video_message, "caption")

    if message_type == "document":
        document_message = _get_mapping(message, "documentMessage")
        caption = _get_str(document_message, "caption")
        if caption is not None:
            return caption

        document_with_caption = _get_mapping(message, "documentWithCaptionMessage")
        nested_message = _get_mapping(document_with_caption, "message")
        nested_document = _get_mapping(nested_message, "documentMessage")

        return _get_str(document_with_caption, "caption") or _get_str(
            nested_document,
            "caption",
        )

    return None


def _extract_media_mimetype(
    message: Mapping[str, object],
    message_type: MessageType,
) -> str | None:
    message_key_by_type = {
        "audio": "audioMessage",
        "image": "imageMessage",
        "video": "videoMessage",
        "document": "documentMessage",
        "sticker": "stickerMessage",
    }

    message_key = message_key_by_type.get(message_type)
    if message_key is None:
        return None

    media_message = _get_mapping(message, message_key)
    mimetype = _get_str(media_message, "mimetype")
    if mimetype is not None:
        return mimetype

    if message_type == "document":
        document_with_caption = _get_mapping(message, "documentWithCaptionMessage")
        nested_message = _get_mapping(document_with_caption, "message")
        nested_document = _get_mapping(nested_message, "documentMessage")
        return _get_str(nested_document, "mimetype")

    return None


def _extract_media(
    message: Mapping[str, object],
    message_type: MessageType,
    key: Mapping[str, object],
) -> NormalizedMedia | None:
    if message_type not in {"audio", "image", "video", "document", "sticker"}:
        return None
    message_key_by_type = {
        "audio": "audioMessage",
        "image": "imageMessage",
        "video": "videoMessage",
        "document": "documentMessage",
        "sticker": "stickerMessage",
    }
    media_message = _get_mapping(message, message_key_by_type[message_type])
    if message_type == "document" and not media_message:
        document_with_caption = _get_mapping(message, "documentWithCaptionMessage")
        nested_message = _get_mapping(document_with_caption, "message")
        media_message = _get_mapping(nested_message, "documentMessage")
    file_size = _extract_file_size(media_message)
    locator = {
        "message_id": _get_str(key, "id"),
        "remote_jid": _get_str(key, "remoteJid"),
        "from_me": _get_bool(key, "fromMe"),
        "message_type": message_key_by_type[message_type],
    }
    locator = {key: value for key, value in locator.items() if value is not None}
    return NormalizedMedia(
        media_type=message_type,
        mimetype=_get_str(media_message, "mimetype"),
        file_name=_get_str(media_message, "fileName") or _get_str(media_message, "file_name"),
        file_size_bytes=file_size,
        inline_base64=_get_str(media_message, "base64"),
        locator=locator,
    )


def _extract_file_size(media_message: Mapping[str, object]) -> int | None:
    for key in ("fileLength", "fileSize", "file_size_bytes"):
        value = media_message.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.isdecimal():
            return int(value)
    return None


def _extract_timestamp(data: Mapping[str, object]) -> int | None:
    value = data.get("messageTimestamp")
    if isinstance(value, int) and not isinstance(value, bool):
        return value

    if isinstance(value, str) and value.isdecimal():
        return int(value)

    return None


def _is_group_jid(remote_jid: str | None) -> bool:
    return remote_jid is not None and remote_jid.endswith("@g.us")


def _extract_phone(remote_jid: str | None, is_group: bool) -> str | None:
    if remote_jid is None or is_group or remote_jid.endswith("@lid"):
        return None

    if "@" not in remote_jid:
        return None

    user_part = remote_jid.split("@", maxsplit=1)[0]
    phone = re.sub(r"\D", "", user_part)

    return phone or None


def _normalize_event_for_comparison(event: str | None) -> str | None:
    if event is None:
        return None

    return event.lower().replace("_", ".")


def _get_ignore_reason(normalized: NormalizedMessage) -> str | None:
    normalized_event = _normalize_event_for_comparison(normalized.event)

    if normalized_event != "messages.upsert":
        return "unsupported_event"
    if normalized.from_me:
        return "from_me"
    if normalized.is_group:
        return "group_message"
    if normalized.message_id is None:
        return "missing_message_id"
    if normalized.message_type not in PROCESSABLE_MESSAGE_TYPES:
        return "unsupported_message_type"
    if normalized.message_type == "text" and not _has_non_empty_text(normalized.text):
        return "empty_text"

    return None


def _has_non_empty_text(text: str | None) -> bool:
    return text is not None and text.strip() != ""
