from datetime import date, time

from pydantic import BaseModel, ConfigDict


class AvailableSlot(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_time: time
    end_time: time
    resource_key: str | None = None
    barber_name: str | None = None


class AvailabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    local_date: date
    timezone: str
    total_duration_minutes: int
    slots: list[AvailableSlot]
