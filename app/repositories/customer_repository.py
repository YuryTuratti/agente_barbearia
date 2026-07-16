from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Customer
from app.domain.scheduling import sanitize_customer_name, validate_instance, validate_phone
from app.schemas.customer import CustomerResult


def _to_result(customer: Customer) -> CustomerResult:
    return CustomerResult(
        id=customer.id,
        instance=customer.instance,
        phone=customer.phone,
        name=customer.name,
    )


async def get_customer_by_phone(
    session: AsyncSession,
    *,
    instance: str,
    phone: str,
) -> CustomerResult | None:
    clean_instance = validate_instance(instance)
    clean_phone = validate_phone(phone)
    result = await session.execute(
        select(Customer).where(
            Customer.instance == clean_instance,
            Customer.phone == clean_phone,
        )
    )
    customer = result.scalar_one_or_none()
    return None if customer is None else _to_result(customer)


async def get_or_create_customer(
    session: AsyncSession,
    *,
    instance: str,
    phone: str,
    name: str | None,
) -> CustomerResult:
    clean_instance = validate_instance(instance)
    clean_phone = validate_phone(phone)
    clean_name = sanitize_customer_name(name)

    result = await session.execute(
        select(Customer).where(
            Customer.instance == clean_instance,
            Customer.phone == clean_phone,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        if clean_name is not None and existing.name != clean_name:
            existing.name = clean_name
        return _to_result(existing)

    try:
        async with session.begin_nested():
            customer = Customer(instance=clean_instance, phone=clean_phone, name=clean_name)
            session.add(customer)
            await session.flush()
        return _to_result(customer)
    except IntegrityError:
        result = await session.execute(
            select(Customer).where(
                Customer.instance == clean_instance,
                Customer.phone == clean_phone,
            )
        )
        existing = result.scalar_one()
        return _to_result(existing)
