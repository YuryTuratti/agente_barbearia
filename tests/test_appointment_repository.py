from datetime import UTC, datetime

import pytest

from app.repositories.appointment_repository import find_overlapping_appointments
from app.services.scheduling_service import SchedulingService
from tests.scheduling_helpers import FakeClock, add_hours, add_service, scheduling_settings


@pytest.mark.anyio
async def test_find_overlapping_appointments_uses_half_open_intervals(db_session):
    service_record = await add_service(db_session, duration_minutes=30)
    await add_hours(db_session)
    scheduler = SchedulingService(
        db_session,
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )
    appointment = await scheduler.create_appointment(
        instance="turatti",
        phone="5534999999999",
        customer_name=None,
        service_ids=[service_record.id],
        local_date=datetime(2026, 7, 10).date(),
        local_start_time=datetime(2026, 7, 10, 8, 0).time(),
    )

    overlapping = await find_overlapping_appointments(
        db_session,
        instance="turatti",
        resource_key="main",
        start_at=datetime(2026, 7, 10, 11, 20, tzinfo=UTC),
        end_at=datetime(2026, 7, 10, 11, 50, tzinfo=UTC),
    )
    adjacent = await find_overlapping_appointments(
        db_session,
        instance="turatti",
        resource_key="main",
        start_at=datetime(2026, 7, 10, 11, 30, tzinfo=UTC),
        end_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
    )

    assert [item.id for item in overlapping] == [appointment.id]
    assert adjacent == []
