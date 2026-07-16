from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ListServicesArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GetBarbershopInfoArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ListAvailableSlotsArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    local_date: date
    service_ids: list[str] = Field(min_length=1)
    barber: str | None = None

    @field_validator("service_ids")
    @classmethod
    def validate_service_ids(cls, value: list[str]) -> list[str]:
        clean_ids = [service_id.strip() for service_id in value]
        if any(not service_id for service_id in clean_ids):
            raise ValueError("Service IDs must not be blank.")
        if len(set(clean_ids)) != len(clean_ids):
            raise ValueError("Service IDs must not be duplicated.")
        return clean_ids


class ListMyAppointmentsArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PrepareCreateAppointmentArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ids: list[str] = Field(min_length=1)
    local_date: date
    local_start_time: str
    customer_name: str | None
    barber: str | None = None

    @field_validator("service_ids")
    @classmethod
    def validate_service_ids(cls, value: list[str]) -> list[str]:
        clean_ids = [service_id.strip() for service_id in value]
        if any(not service_id for service_id in clean_ids):
            raise ValueError("Service IDs must not be blank.")
        if len(set(clean_ids)) != len(clean_ids):
            raise ValueError("Service IDs must not be duplicated.")
        return clean_ids


class PrepareCancelAppointmentArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    appointment_id: str
    reason: str | None


class PrepareRescheduleAppointmentArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    appointment_id: str
    new_local_date: date
    new_local_start_time: str
    barber: str | None = None


class ConfirmPendingActionArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DiscardPendingActionArguments(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolErrorResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    retryable: bool = False


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    tool_name: str
    data: dict[str, object] | None = None
    error: ToolErrorResult | None = None
