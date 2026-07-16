from datetime import UTC, date, datetime, time

import pytest

from app.database.models import Appointment
from app.exceptions.scheduling import BookingTooFarAheadError, InvalidAppointmentTimeError
from app.services.availability_service import AvailabilityService
from tests.scheduling_helpers import FakeClock, add_hours, add_service, scheduling_settings


@pytest.mark.anyio
async def test_availability_calculates_single_and_multiple_service_duration(db_session):
    first = await add_service(db_session, slug="corte", duration_minutes=30)
    second = await add_service(db_session, slug="barba", duration_minutes=20)
    await add_hours(db_session, opens_at=time(8, 0), closes_at=time(9, 0))
    service = AvailabilityService(
        db_session,
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )

    one = await service.list_available_slots(
        instance="turatti",
        local_date=date(2026, 7, 10),
        service_ids=[first.id],
    )
    two = await service.list_available_slots(
        instance="turatti",
        local_date=date(2026, 7, 10),
        service_ids=[first.id, second.id],
    )

    assert one.total_duration_minutes == 30
    assert two.total_duration_minutes == 50
    assert one.slots[0].start_time == time(8, 0)
    assert two.slots[-1].start_time == time(8, 10)


@pytest.mark.anyio
async def test_availability_returns_no_slots_without_business_hours(db_session):
    service_record = await add_service(db_session)
    service = AvailabilityService(
        db_session,
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )

    result = await service.list_available_slots(
        instance="turatti",
        local_date=date(2026, 7, 10),
        service_ids=[service_record.id],
    )

    assert result.slots == []


@pytest.mark.anyio
async def test_availability_rejects_past_and_too_far_dates(db_session):
    service_record = await add_service(db_session)
    service = AvailabilityService(
        db_session,
        settings=scheduling_settings(scheduling_max_days_ahead=1),
        clock=FakeClock(datetime(2026, 7, 10, 12, 0, tzinfo=UTC)),
    )

    with pytest.raises(InvalidAppointmentTimeError):
        await service.list_available_slots(
            instance="turatti",
            local_date=date(2026, 7, 9),
            service_ids=[service_record.id],
        )
    with pytest.raises(BookingTooFarAheadError):
        await service.list_available_slots(
            instance="turatti",
            local_date=date(2026, 7, 12),
            service_ids=[service_record.id],
        )


@pytest.mark.anyio
async def test_availability_respects_notice_lunch_interval_and_scheduled_blocks(db_session):
    service_record = await add_service(db_session, duration_minutes=30)
    await add_hours(db_session, opens_at=time(8, 0), closes_at=time(9, 0))
    await add_hours(db_session, opens_at=time(10, 0), closes_at=time(11, 0))
    customer_id = "customer-id"
    from app.database.models import Customer

    db_session.add(Customer(id=customer_id, instance="turatti", phone="5534999999999"))
    db_session.add(
        Appointment(
            instance="turatti",
            resource_key="main",
            customer_id=customer_id,
            confirmation_code="ABCDEFGH",
            status="scheduled",
            start_at=datetime(2026, 7, 10, 11, 10, tzinfo=UTC),
            end_at=datetime(2026, 7, 10, 11, 40, tzinfo=UTC),
            total_duration_minutes=30,
            total_price_cents=3500,
        )
    )
    db_session.add(
        Appointment(
            instance="turatti",
            resource_key="main",
            customer_id=customer_id,
            confirmation_code="BCDEFGHJ",
            status="cancelled",
            start_at=datetime(2026, 7, 10, 11, 40, tzinfo=UTC),
            end_at=datetime(2026, 7, 10, 12, 10, tzinfo=UTC),
            total_duration_minutes=30,
            total_price_cents=3500,
        )
    )
    await db_session.commit()

    service = AvailabilityService(
        db_session,
        settings=scheduling_settings(scheduling_min_notice_minutes=30),
        clock=FakeClock(datetime(2026, 7, 10, 10, 30, tzinfo=UTC)),
    )
    result = await service.list_available_slots(
        instance="turatti",
        local_date=date(2026, 7, 10),
        service_ids=[service_record.id],
    )

    starts = [slot.start_time for slot in result.slots]
    assert time(8, 0) not in starts
    assert time(8, 10) not in starts
    assert time(8, 40) not in starts
    assert time(10, 0) in starts
    assert time(10, 10) in starts
    assert starts == sorted(starts)
