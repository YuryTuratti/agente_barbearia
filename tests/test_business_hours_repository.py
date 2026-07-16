from datetime import time

import pytest
from sqlalchemy.exc import IntegrityError

from app.database.models import BusinessHours
from app.exceptions.scheduling import InvalidAppointmentTimeError
from app.repositories.business_hours_repository import list_business_hours_for_weekday
from tests.scheduling_helpers import add_hours


@pytest.mark.anyio
async def test_list_business_hours_returns_active_ordered_intervals(db_session):
    await add_hours(db_session, opens_at=time(13, 0), closes_at=time(18, 0))
    await add_hours(db_session, opens_at=time(8, 0), closes_at=time(11, 0))
    await add_hours(db_session, opens_at=time(18, 0), closes_at=time(19, 0), active=False)

    intervals = await list_business_hours_for_weekday(
        db_session,
        instance="turatti",
        resource_key="main",
        weekday=4,
    )

    assert [(item.opens_at, item.closes_at) for item in intervals] == [
        (time(8, 0), time(11, 0)),
        (time(13, 0), time(18, 0)),
    ]


@pytest.mark.anyio
async def test_business_hours_reject_invalid_weekday_and_invalid_interval(db_session):
    with pytest.raises(InvalidAppointmentTimeError):
        await list_business_hours_for_weekday(
            db_session,
            instance="turatti",
            resource_key="main",
            weekday=7,
        )

    db_session.add(
        BusinessHours(
            instance="turatti",
            resource_key="main",
            weekday=7,
            opens_at=time(8, 0),
            closes_at=time(9, 0),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    db_session.add(
        BusinessHours(
            instance="turatti",
            resource_key="main",
            weekday=4,
            opens_at=time(9, 0),
            closes_at=time(9, 0),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.anyio
async def test_business_hours_allows_two_intervals_but_rejects_exact_duplicate(db_session):
    await add_hours(db_session, opens_at=time(8, 0), closes_at=time(11, 0))
    await add_hours(db_session, opens_at=time(13, 0), closes_at=time(18, 0))
    db_session.add(
        BusinessHours(
            instance="turatti",
            resource_key="main",
            weekday=4,
            opens_at=time(8, 0),
            closes_at=time(11, 0),
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.commit()
