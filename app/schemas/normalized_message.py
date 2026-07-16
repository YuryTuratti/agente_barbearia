from typing import Literal

from pydantic import BaseModel, ConfigDict

MessageType = Literal[
    "text",
    "audio",
    "image",
    "video",
    "document",
    "sticker",
    "unknown",
]


class NormalizedMedia(BaseModel):
    model_config = ConfigDict(frozen=True)

    media_type: Literal["audio", "image", "video", "document", "sticker"]
    mimetype: str | None = None
    file_name: str | None = None
    file_size_bytes: int | None = None
    inline_base64: str | None = None
    locator: dict[str, object]


class NormalizedMessage(BaseModel):
    event: str | None = None
    instance: str | None = None
    message_id: str | None = None
    remote_jid: str | None = None
    phone: str | None = None
    sender_name: str | None = None
    from_me: bool = False
    is_group: bool = False
    message_type: MessageType = "unknown"
    text: str | None = None
    media_mimetype: str | None = None
    media: NormalizedMedia | None = None
    timestamp: int | None = None
    processable: bool = False
    ignore_reason: str | None = None
