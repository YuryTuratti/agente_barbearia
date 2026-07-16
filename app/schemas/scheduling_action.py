from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateAppointmentActionPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ids: list[str] = Field(min_length=1)
    local_date: date
    local_start_time: time
    customer_name: str | None
    resource_key: str = "main"

    @field_validator("service_ids")
    @classmethod
    def validate_service_ids(cls, value: list[str]) -> list[str]:
        clean_ids = [service_id.strip() for service_id in value]
        if any(not service_id for service_id in clean_ids):
            raise ValueError("Service IDs must not be blank.")
        if len(set(clean_ids)) != len(clean_ids):
            raise ValueError("Service IDs must not be duplicated.")
        return clean_ids


class CancelAppointmentActionPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    appointment_id: str
    reason: str | None

    @field_validator("appointment_id")
    @classmethod
    def validate_appointment_id(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Appointment ID is required.")
        return clean


class RescheduleAppointmentActionPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    appointment_id: str
    new_local_date: date
    new_local_start_time: time
    resource_key: str | None = None

    @field_validator("appointment_id")
    @classmethod
    def validate_appointment_id(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Appointment ID is required.")
        return clean


class PendingActionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_type: Literal["create", "cancel", "reschedule"]
    status: str
    confirmation_required: bool
    expires_at: datetime
    summary: dict[str, Any]


class SchedulingActionExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_type: Literal["create", "cancel", "reschedule"]
    status: str
    appointment_id: str | None
    summary: dict[str, Any]
