from datetime import date, datetime, time, UTC
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.database.models import BarbershopResource, BusinessHours, Service
from app.domain.barbershop_catalog import seed_confirmed_barbershop
from tests.scheduling_helpers import FakeClock
from app.services.availability_service import AvailabilityService
from app.services.scheduling_service import SchedulingService
from app.repositories.barbershop_resource_repository import normalize_barber, resource_display_name
from app.prompts.carlos_scheduling import CARLOS_SCHEDULING_SYSTEM_PROMPT
from app.prompts.carlos_scheduling_write import CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT


@pytest.mark.anyio
async def test_seed_creates_daniel_and_split_lunch_idempotently(session_maker):
    async with session_maker() as session:
        first = await seed_confirmed_barbershop(session, instance="shop")
        second = await seed_confirmed_barbershop(session, instance="shop")
        await session.commit()
        resources = {item.resource_key: item for item in (await session.execute(select(BarbershopResource))).scalars().all()}
        daniel = resources["daniel"]
        hours = list((await session.execute(select(BusinessHours).where(BusinessHours.resource_key == "daniel", BusinessHours.active.is_(True)))).scalars())
    assert daniel.display_name == "Daniel" and daniel.is_active and daniel.booking_enabled
    assert resources["main"].display_name == "Lucas"
    assert first["resources_created"] == 2 and second["resources_created"] == 0
    assert {item.weekday for item in hours} == {0, 2, 3, 4, 5}
    assert 1 not in {item.weekday for item in hours} and 6 not in {item.weekday for item in hours}
    assert all(item.closes_at <= time(12) or item.opens_at >= time(13) for item in hours)


@pytest.mark.anyio
async def test_daniel_availability_excludes_lunch_and_unspecified_returns_both(session_maker):
    async with session_maker() as session:
        await seed_confirmed_barbershop(session, instance="shop")
        await session.commit()
        service_id = str((await session.execute(select(Service))).scalars().first().id)
        await session.commit()
        service = AvailabilityService(session, settings=Settings(scheduling_min_notice_minutes=0), clock=FakeClock(datetime(2026, 7, 12, tzinfo=UTC)))
        daniel = await service.list_available_slots(instance="shop", local_date=date(2026, 7, 13), service_ids=[service_id], resource_key="daniel")
        all_slots = await service.list_available_slots(instance="shop", local_date=date(2026, 7, 15), service_ids=[service_id])
    assert daniel.slots and all(slot.resource_key == "daniel" for slot in daniel.slots)
    assert all(not (time(12) <= slot.start_time < time(13)) for slot in daniel.slots)
    assert {slot.resource_key for slot in all_slots.slots} == {"main", "daniel"}


def test_lucas_aliases_keep_main_resource_key_and_public_names():
    assert normalize_barber("lucas") == "main"
    assert normalize_barber("main") == "main"
    assert normalize_barber("barbeiro principal") == "main"
    assert normalize_barber("o principal") == "main"
    assert normalize_barber("daniel") == "daniel"
    assert normalize_barber("qualquer") is None
    assert resource_display_name("main") == "Lucas"
    assert resource_display_name("daniel") == "Daniel"


def test_prompts_publish_lucas_and_daniel_without_old_public_name():
    for prompt in (CARLOS_SCHEDULING_SYSTEM_PROMPT, CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT):
        assert "- Lucas" in prompt
        assert "- Daniel" in prompt
        assert "Barbeiros disponíveis" in prompt
        assert "Barbeiro principal e Daniel" not in prompt


def test_admin_filters_show_lucas_and_daniel():
    templates = Path("app/templates/admin")
    for name in ("agenda.html", "servicos.html", "faturamento.html", "horarios.html", "cancelamentos.html"):
        content = (templates / name).read_text(encoding="utf-8")
        assert '<option value="main">Lucas</option>' in content
        assert '<option value="daniel">Daniel</option>' in content
        assert "Barbeiro principal</option>" not in content


@pytest.mark.anyio
async def test_appointments_with_lucas_and_daniel_keep_resource_keys(session_maker):
    async with session_maker() as session:
        await seed_confirmed_barbershop(session, instance="shop")
        await session.commit()
        service_id = str((await session.execute(select(Service))).scalars().first().id)
        await session.commit()
        scheduler = SchedulingService(session, settings=Settings(scheduling_min_notice_minutes=0), clock=FakeClock(datetime(2026, 7, 12, tzinfo=UTC)))
        lucas = await scheduler.create_appointment(instance="shop", phone="5511999990001", customer_name="Cliente Lucas", service_ids=[service_id], local_date=date(2026, 7, 15), local_start_time=time(10), resource_key="main")
        daniel = await scheduler.create_appointment(instance="shop", phone="5511999990002", customer_name="Cliente Daniel", service_ids=[service_id], local_date=date(2026, 7, 15), local_start_time=time(10), resource_key="daniel")
    assert lucas.resource_key == "main" and lucas.barber_name == "Lucas"
    assert daniel.resource_key == "daniel" and daniel.barber_name == "Daniel"
