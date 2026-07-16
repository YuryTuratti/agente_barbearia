from datetime import UTC, date, datetime, time

import pytest

from app.domain.scheduling import combine_local_datetime, to_utc
from app.services.scheduling_service import SchedulingService
from tests.scheduling_helpers import FakeClock, add_hours, add_service, scheduling_settings


def test_local_datetime_converts_to_utc_without_system_timezone():
    local_value = combine_local_datetime(
        date(2026, 7, 10),
        time(14, 30),
        "America/Sao_Paulo",
    )

    assert to_utc(local_value).hour == 17


@pytest.mark.anyio
async def test_scheduling_returns_local_date_even_when_utc_day_differs(db_session):
    service_record = await add_service(db_session, duration_minutes=30)
    await add_hours(db_session, opens_at=time(21, 0), closes_at=time(23, 0))
    scheduler = SchedulingService(
        db_session,
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )

    result = await scheduler.create_appointment(
        instance="turatti",
        phone="5534999999999",
        customer_name=None,
        service_ids=[service_record.id],
        local_date=date(2026, 7, 10),
        local_start_time=time(22, 30),
    )

    assert result.local_date == date(2026, 7, 10)
    assert result.local_start_time == time(22, 30)
