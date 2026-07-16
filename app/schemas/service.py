from pydantic import BaseModel, ConfigDict


class ServiceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    slug: str
    name: str
    description: str | None
    duration_minutes: int
    price_cents: int
    booking_enabled: bool = True
    price_type: str = "fixed"
    requires_quote: bool = False
