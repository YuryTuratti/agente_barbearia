from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ConversationMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
