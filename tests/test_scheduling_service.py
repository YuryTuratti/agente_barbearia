from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select

from app.database.models import Appointment, AppointmentService, Customer, Service
from app.exceptions.scheduling import (
    AppointmentNotScheduledError,
    AppointmentOwnershipError,
    BookingNoticeError,
    BookingTooFarAheadError,
    InactiveServiceError,
    InvalidPhoneError,
    OutsideBusinessHoursError,
    ServiceNotFoundError,
    SlotUnavailableError,
)
from app.services.scheduling_service import SchedulingService
from tests.scheduling_helpers import FakeClock, add_hours, add_service, scheduling_settings


def make_service(db_session, **settings):
    return SchedulingService(
        db_session,
        settings=scheduling_settings(**settings),
        clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )


@pytest.mark.anyio
async def test_create_appointment_with_multiple_services_snapshots_and_customer(db_session):
    first = await add_service(db_session, slug="corte", name="Corte", duration_minutes=30, price_cents=3500)
    second = await add_service(db_session, slug="barba", name="Barba", duration_minutes=20, price_cents=2000)
    await add_hours(db_session, opens_at=time(8, 0), closes_at=time(18, 0))

    result = await make_service(db_session).create_appointment(
        instance="turatti",
        phone="5534999999999",
        customer_name=" Cliente ",
        service_ids=[first.id, second.id],
        local_date=date(2026, 7, 10),
        local_start_time=time(8, 0),
    )

    assert result.created is True
    assert result.idempotent_replay is False
    assert result.status == "scheduled"
    assert result.local_end_time == time(8, 50)
    assert result.total_duration_minutes == 50
    assert result.total_price_cents == 5500
    assert result.confirmation_code.isalnum()
    assert [snapshot.service_id for snapshot in result.services] == [first.id, second.id]
    assert [snapshot.name for snapshot in result.services] == ["Corte", "Barba"]

    customers = (await db_session.execute(select(Customer))).scalars().all()
    snapshots = (await db_session.execute(select(AppointmentService))).scalars().all()
    assert len(customers) == 1
    assert customers[0].phone == "5534999999999"
    assert [snapshot.position for snapshot in snapshots] == [0, 1]


@pytest.mark.anyio
async def test_create_appointment_reuses_customer_and_keeps_snapshots_after_catalog_change(db_session):
    service_record = await add_service(db_session, name="Corte", duration_minutes=30, price_cents=3500)
    await add_hours(db_session)
    scheduler = make_service(db_session)

    first = await scheduler.create_appointment(
        instance="turatti",
        phone="5534999999999",
        customer_name="Ana",
        service_ids=[service_record.id],
        local_date=date(2026, 7, 10),
        local_start_time=time(8, 0),
    )
    service_record.name = "Corte alterado"
    service_record.duration_minutes = 60
    service_record.price_cents = 9999
    await db_session.commit()
    second = await scheduler.create_appointment(
        instance="turatti",
        phone="5534999999999",
        customer_name="",
        service_ids=[service_record.id],
        local_date=date(2026, 7, 10),
        local_start_time=time(9, 0),
    )

    customers = (await db_session.execute(select(Customer))).scalars().all()
    assert len(customers) == 1
    assert first.services[0].name == "Corte"
    assert first.total_price_cents == 3500
    assert second.services[0].name == "Corte alterado"


@pytest.mark.anyio
async def test_create_appointment_rejects_invalid_inputs(db_session):
    active = await add_service(db_session)
    inactive = await add_service(db_session, slug="inativo", active=False)
    active_id = active.id
    inactive_id = inactive.id
    await add_hours(db_session, opens_at=time(8, 0), closes_at=time(9, 0))
    scheduler = make_service(db_session, scheduling_min_notice_minutes=60, scheduling_max_days_ahead=1, scheduling_max_services_per_appointment=1)

    with pytest.raises(InvalidPhoneError):
            await scheduler.create_appointment(instance="turatti", phone="bad", customer_name=None, service_ids=[active_id], local_date=date(2026, 7, 10), local_start_time=time(8, 0))
    with pytest.raises(ServiceNotFoundError):
        await scheduler.create_appointment(instance="turatti", phone="5534999999999", customer_name=None, service_ids=[], local_date=date(2026, 7, 10), local_start_time=time(8, 0))
    with pytest.raises(ServiceNotFoundError):
            await scheduler.create_appointment(instance="turatti", phone="5534999999999", customer_name=None, service_ids=[active_id, active_id], local_date=date(2026, 7, 10), local_start_time=time(8, 0))
    with pytest.raises(InactiveServiceError):
            await scheduler.create_appointment(instance="turatti", phone="5534999999999", customer_name=None, service_ids=[inactive_id], local_date=date(2026, 7, 10), local_start_time=time(8, 0))
    with pytest.raises(OutsideBusinessHoursError):
        await scheduler.create_appointment(instance="turatti", phone="5534999999999", customer_name=None, service_ids=[active_id], local_date=date(2026, 7, 10), local_start_time=time(8, 40))
    with pytest.raises(BookingNoticeError):
        await scheduler.create_appointment(instance="turatti", phone="5534999999999", customer_name=None, service_ids=[active_id], local_date=date(2026, 7, 10), local_start_time=time(3, 30))
    with pytest.raises(BookingTooFarAheadError):
        await scheduler.create_appointment(instance="turatti", phone="5534999999999", customer_name=None, service_ids=[active_id], local_date=date(2026, 7, 12), local_start_time=time(8, 0))


@pytest.mark.anyio
async def test_conflict_blocks_overlap_and_allows_adjacent(db_session):
    service_record = await add_service(db_session, duration_minutes=30)
    service_id = service_record.id
    await add_hours(db_session)
    scheduler = make_service(db_session)

    await scheduler.create_appointment(instance="turatti", phone="5534999999999", customer_name=None, service_ids=[service_id], local_date=date(2026, 7, 10), local_start_time=time(8, 0))
    with pytest.raises(SlotUnavailableError):
        await scheduler.create_appointment(instance="turatti", phone="5534888888888", customer_name=None, service_ids=[service_id], local_date=date(2026, 7, 10), local_start_time=time(8, 20))
    adjacent = await scheduler.create_appointment(instance="turatti", phone="5534777777777", customer_name=None, service_ids=[service_id], local_date=date(2026, 7, 10), local_start_time=time(8, 30))

    assert adjacent.local_start_time == time(8, 30)
    await scheduler.create_appointment(instance="turatti", phone="5534666666666", customer_name=None, service_ids=[service_id], local_date=date(2026, 7, 10), local_start_time=time(9, 0))


@pytest.mark.anyio
async def test_list_future_cancel_and_reschedule_appointments(db_session):
    service_record = await add_service(db_session, duration_minutes=30)
    await add_hours(db_session)
    scheduler = make_service(db_session)
    appointment = await scheduler.create_appointment(instance="turatti", phone="5534999999999", customer_name="Ana", service_ids=[service_record.id], local_date=date(2026, 7, 10), local_start_time=time(8, 0))
    await scheduler.create_appointment(instance="turatti", phone="5534888888888", customer_name=None, service_ids=[service_record.id], local_date=date(2026, 7, 10), local_start_time=time(9, 0))

    listed = await scheduler.list_future_appointments(instance="turatti", phone="5534999999999")
    assert [item.id for item in listed] == [appointment.id]

    rescheduled = await scheduler.reschedule_appointment(instance="turatti", phone="5534999999999", appointment_id=appointment.id, new_local_date=date(2026, 7, 10), new_local_start_time=time(8, 30))
    assert rescheduled.id == appointment.id
    assert rescheduled.confirmation_code == appointment.confirmation_code
    assert rescheduled.local_start_time == time(8, 30)

    with pytest.raises(AppointmentOwnershipError):
        await scheduler.cancel_appointment(instance="turatti", phone="5534000000000", appointment_id=appointment.id)
    cancelled = await scheduler.cancel_appointment(instance="turatti", phone="5534999999999", appointment_id=appointment.id, reason="x" * 600)
    assert cancelled.status == "cancelled"
    row = await db_session.get(Appointment, appointment.id)
    assert row is not None
    assert row.cancelled_at is not None
    assert len(row.cancellation_reason) == 500
    await db_session.rollback()
    with pytest.raises(AppointmentNotScheduledError):
        await scheduler.cancel_appointment(instance="turatti", phone="5534999999999", appointment_id=appointment.id)
