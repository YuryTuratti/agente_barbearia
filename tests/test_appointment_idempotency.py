from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select

from app.database.models import Appointment, AppointmentService
from app.exceptions.scheduling import IdempotencyConflictError
from app.services.scheduling_service import SchedulingService
from tests.scheduling_helpers import FakeClock, add_hours, add_service, scheduling_settings


def scheduler(db_session):
    return SchedulingService(
        db_session,
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )


@pytest.mark.anyio
async def test_idempotent_create_replay_does_not_duplicate_appointment_or_snapshots(db_session):
    service_record = await add_service(db_session)
    await add_hours(db_session)

    first = await scheduler(db_session).create_appointment(
        instance="turatti",
        phone="5534999999999",
        customer_name=None,
        service_ids=[service_record.id],
        local_date=date(2026, 7, 10),
        local_start_time=time(8, 0),
        idempotency_key="create-1",
    )
    replay = await scheduler(db_session).create_appointment(
        instance="turatti",
        phone="5534999999999",
        customer_name="Outro nome",
        service_ids=[service_record.id],
        local_date=date(2026, 7, 10),
        local_start_time=time(8, 0),
        idempotency_key="create-1",
    )

    appointments = (await db_session.execute(select(Appointment))).scalars().all()
    snapshots = (await db_session.execute(select(AppointmentService))).scalars().all()
    assert first.created is True
    assert replay.created is False
    assert replay.idempotent_replay is True
    assert replay.id == first.id
    assert len(appointments) == 1
    assert len(snapshots) == 1


@pytest.mark.anyio
async def test_idempotent_create_rejects_same_key_with_different_parameters(db_session):
    first_service = await add_service(db_session, slug="corte")
    second_service = await add_service(db_session, slug="barba")
    first_service_id = first_service.id
    second_service_id = second_service.id
    await add_hours(db_session)
    service = scheduler(db_session)

    await service.create_appointment(
        instance="turatti",
        phone="5534999999999",
        customer_name=None,
        service_ids=[first_service_id],
        local_date=date(2026, 7, 10),
        local_start_time=time(8, 0),
        idempotency_key="create-1",
    )

    with pytest.raises(IdempotencyConflictError):
        await service.create_appointment(
            instance="turatti",
            phone="5534888888888",
            customer_name=None,
            service_ids=[first_service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 0),
            idempotency_key="create-1",
        )
    with pytest.raises(IdempotencyConflictError):
        await service.create_appointment(
            instance="turatti",
            phone="5534999999999",
            customer_name=None,
            service_ids=[second_service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 0),
            idempotency_key="create-1",
        )
    with pytest.raises(IdempotencyConflictError):
        await service.create_appointment(
            instance="turatti",
            phone="5534999999999",
            customer_name=None,
            service_ids=[first_service_id],
            local_date=date(2026, 7, 10),
            local_start_time=time(8, 30),
            idempotency_key="create-1",
        )

    second = await service.create_appointment(
        instance="turatti",
        phone="5534999999999",
        customer_name=None,
        service_ids=[first_service_id],
        local_date=date(2026, 7, 10),
        local_start_time=time(8, 30),
        idempotency_key="create-2",
    )
    assert second.id != ""
