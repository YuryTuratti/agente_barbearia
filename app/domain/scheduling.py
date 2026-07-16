from datetime import UTC, date, datetime, time, timedelta, timezone
import secrets
from zoneinfo import ZoneInfo

from app.exceptions.scheduling import (
    BookingNoticeError,
    BookingTooFarAheadError,
    BusinessClosedError,
    InvalidAppointmentTimeError,
    InvalidPhoneError,
    OutsideBusinessHoursError,
)
from app.schemas.business_hours import BusinessHoursInterval
from app.schemas.service import ServiceSummary

CONFIRMATION_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_CUSTOMER_NAME_LENGTH = 120
MAX_CANCELLATION_REASON_LENGTH = 500


def validate_instance(value: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise InvalidAppointmentTimeError("Instance is required.")
    return clean_value


def validate_resource_key(value: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise InvalidAppointmentTimeError("Resource key is required.")
    return clean_value


def validate_phone(value: str) -> str:
    clean_value = value.strip()
    if not clean_value or not clean_value.isdigit():
        raise InvalidPhoneError("Phone must contain only digits.")
    return clean_value


def sanitize_customer_name(value: str | None) -> str | None:
    if value is None:
        return None
    clean_value = value.strip()
    if not clean_value:
        return None
    return clean_value[:MAX_CUSTOMER_NAME_LENGTH]


def sanitize_cancellation_reason(value: str | None) -> str | None:
    if value is None:
        return None
    clean_value = value.strip()
    if not clean_value:
        return None
    return clean_value[:MAX_CANCELLATION_REASON_LENGTH]


def generate_confirmation_code(length: int) -> str:
    return "".join(secrets.choice(CONFIRMATION_CODE_ALPHABET) for _ in range(length))


def get_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        if timezone_name == "America/Sao_Paulo":
            return timezone(timedelta(hours=-3), name=timezone_name)
        raise


def combine_local_datetime(local_date: date, local_time: time, timezone_name: str) -> datetime:
    if local_time.tzinfo is not None:
        raise InvalidAppointmentTimeError("Local time must not include timezone information.")
    zone = get_timezone(timezone_name)
    return datetime.combine(local_date, local_time, tzinfo=zone)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise InvalidAppointmentTimeError("Datetime must include timezone information.")
    return value.astimezone(UTC)


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def validate_booking_window(
    *,
    local_start: datetime,
    now_utc: datetime,
    min_notice_minutes: int,
    max_days_ahead: int,
    timezone_name: str,
) -> None:
    now_local = ensure_aware_utc(now_utc).astimezone(get_timezone(timezone_name))
    if local_start < now_local + timedelta(minutes=min_notice_minutes):
        raise BookingNoticeError("Appointment does not satisfy the minimum booking notice.")
    if local_start.date() > now_local.date() + timedelta(days=max_days_ahead):
        raise BookingTooFarAheadError("Appointment is beyond the maximum scheduling window.")


def validate_availability_date(
    *,
    local_date: date,
    now_utc: datetime,
    max_days_ahead: int,
    timezone_name: str,
) -> None:
    today = ensure_aware_utc(now_utc).astimezone(get_timezone(timezone_name)).date()
    if local_date < today:
        raise InvalidAppointmentTimeError("Date is in the past.")
    if local_date > today + timedelta(days=max_days_ahead):
        raise BookingTooFarAheadError("Date is beyond the maximum scheduling window.")


def total_duration_minutes(services: list[ServiceSummary]) -> int:
    return sum(service.duration_minutes for service in services)


def total_price_cents(services: list[ServiceSummary]) -> int:
    return sum(service.price_cents for service in services)


def interval_overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and end_a > start_b


def local_interval_fits_business_hours(
    *,
    local_start: datetime,
    local_end: datetime,
    intervals: list[BusinessHoursInterval],
) -> bool:
    start_time = local_start.timetz().replace(tzinfo=None)
    end_time = local_end.timetz().replace(tzinfo=None)
    if local_start.date() != local_end.date():
        return False
    return any(interval.opens_at <= start_time and end_time <= interval.closes_at for interval in intervals)


def require_fits_business_hours(
    *,
    local_start: datetime,
    local_end: datetime,
    intervals: list[BusinessHoursInterval],
) -> None:
    if not intervals:
        raise BusinessClosedError("Business is closed on this day.")
    if not local_interval_fits_business_hours(
        local_start=local_start,
        local_end=local_end,
        intervals=intervals,
    ):
        raise OutsideBusinessHoursError("Appointment is outside business hours.")


def add_minutes_to_time(value: time, minutes: int) -> time:
    base = datetime.combine(date(2000, 1, 1), value)
    return (base + timedelta(minutes=minutes)).time()
