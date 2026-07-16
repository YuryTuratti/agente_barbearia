import pytest
from sqlalchemy.exc import IntegrityError

from app.database.models import Service
from app.exceptions.scheduling import InactiveServiceError, ServiceNotFoundError
from app.repositories.service_repository import get_active_services_by_ids, list_active_services
from tests.scheduling_helpers import add_service


@pytest.mark.anyio
async def test_list_active_services_ignores_inactive(db_session):
    active = await add_service(db_session, slug="ativo", name="Ativo")
    await add_service(db_session, slug="inativo", name="Inativo", active=False)

    services = await list_active_services(db_session)

    assert [service.id for service in services] == [active.id]


@pytest.mark.anyio
async def test_service_constraints_reject_invalid_duration_and_price(db_session):
    db_session.add(Service(slug="zero", name="Zero", duration_minutes=0, price_cents=0))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    db_session.add(Service(slug="negativo", name="Negativo", duration_minutes=10, price_cents=-1))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.anyio
async def test_service_slug_is_unique(db_session):
    await add_service(db_session, slug="corte")
    db_session.add(Service(slug="corte", name="Outro", duration_minutes=10, price_cents=1000))

    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.anyio
async def test_get_active_services_by_ids_preserves_order_and_rejects_invalid(db_session):
    first = await add_service(db_session, slug="primeiro")
    second = await add_service(db_session, slug="segundo")
    inactive = await add_service(db_session, slug="inativo", active=False)

    services = await get_active_services_by_ids(
        db_session,
        service_ids=[second.id, first.id],
    )

    assert [service.id for service in services] == [second.id, first.id]
    with pytest.raises(ServiceNotFoundError):
        await get_active_services_by_ids(db_session, service_ids=["missing"])
    with pytest.raises(InactiveServiceError):
        await get_active_services_by_ids(db_session, service_ids=[inactive.id])
    with pytest.raises(ServiceNotFoundError):
        await get_active_services_by_ids(db_session, service_ids=[first.id, first.id])
