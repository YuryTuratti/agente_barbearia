from typing import Literal

from pydantic import BaseModel, ConfigDict


class DownloadedMedia(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    content: bytes
    mimetype: str | None
    file_name: str | None
    size_bytes: int
    sha256: str
    source: Literal["inline_base64", "evolution_api"]


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    provider: str = "openai"
    model: str
