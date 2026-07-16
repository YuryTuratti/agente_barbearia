from datetime import date, time

from pydantic import BaseModel, ConfigDict


class AppointmentServiceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    service_id: str
    name: str
    duration_minutes: int
    price_cents: int


class AppointmentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    resource_key: str = "main"
    barber_name: str = "Lucas"
    confirmation_code: str
    status: str
    local_date: date
    local_start_time: time
    local_end_time: time
    timezone: str
    services: list[AppointmentServiceSnapshot]
    total_duration_minutes: int
    total_price_cents: int
    created: bool
    idempotent_replay: bool
