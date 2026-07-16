from pydantic import BaseModel


class InboundMessageRegistrationResult(BaseModel):
    created: bool
    duplicate: bool
    record_id: int | str | None = None
