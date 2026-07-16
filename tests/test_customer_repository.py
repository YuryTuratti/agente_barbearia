import pytest

from app.exceptions.scheduling import InvalidPhoneError
from app.repositories.customer_repository import get_customer_by_phone, get_or_create_customer


@pytest.mark.anyio
async def test_get_or_create_customer_creates_and_keeps_phone_as_string(db_session):
    customer = await get_or_create_customer(
        db_session,
        instance="turatti",
        phone="5534999999999",
        name=" Cliente ",
    )
    await db_session.commit()

    assert customer.phone == "5534999999999"
    assert customer.name == "Cliente"


@pytest.mark.anyio
async def test_get_or_create_customer_rejects_invalid_phone(db_session):
    with pytest.raises(InvalidPhoneError):
        await get_or_create_customer(
            db_session,
            instance="turatti",
            phone="55-34",
            name=None,
        )


@pytest.mark.anyio
async def test_get_or_create_customer_does_not_duplicate_same_instance_phone(db_session):
    first = await get_or_create_customer(
        db_session,
        instance="turatti",
        phone="5534999999999",
        name="Ana",
    )
    second = await get_or_create_customer(
        db_session,
        instance="turatti",
        phone="5534999999999",
        name="",
    )
    await db_session.commit()

    assert second.id == first.id
    assert second.name == "Ana"


@pytest.mark.anyio
async def test_get_or_create_customer_allows_same_phone_in_different_instances(db_session):
    first = await get_or_create_customer(
        db_session,
        instance="turatti",
        phone="5534999999999",
        name=None,
    )
    second = await get_or_create_customer(
        db_session,
        instance="outra",
        phone="5534999999999",
        name=None,
    )
    await db_session.commit()

    assert first.id != second.id


@pytest.mark.anyio
async def test_get_customer_by_phone_returns_existing_customer(db_session):
    created = await get_or_create_customer(
        db_session,
        instance="turatti",
        phone="5534999999999",
        name="Ana",
    )
    await db_session.commit()

    found = await get_customer_by_phone(
        db_session,
        instance="turatti",
        phone="5534999999999",
    )

    assert found == created
