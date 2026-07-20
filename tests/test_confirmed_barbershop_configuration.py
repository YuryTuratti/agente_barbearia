from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import select

from app.cli.check_barbershop_configuration import main as check_configuration_main
from app.database.models import Appointment, BusinessHours, InboundMessage, Service
from app.domain.barbershop_catalog import (
    SERVICE_CATALOG,
    check_seed_configuration,
    load_seed_file,
    seed_confirmed_barbershop,
    seed_confirmed_services,
)
from app.prompts.carlos_scheduling_write import CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT
from app.prompts.carlos import CARLOS_SYSTEM_PROMPT
from app.prompts.carlos_scheduling import CARLOS_SCHEDULING_SYSTEM_PROMPT
from app.services.scheduling_action_service import SchedulingActionService
from app.tools.scheduling_definitions import (
    GET_BARBERSHOP_INFO_TOOL_NAME,
    LIST_AVAILABLE_SLOTS_TOOL_NAME,
    LIST_SERVICES_TOOL_NAME,
)
from app.tools.scheduling_executor import SchedulingToolExecutor
from app.tools.scheduling_write_definitions import (
    CONFIRM_PENDING_ACTION_TOOL_NAME,
    PREPARE_CREATE_APPOINTMENT_TOOL_NAME,
)
from app.tools.scheduling_write_executor import SchedulingWriteToolExecutor
from tests.scheduling_helpers import FakeClock, scheduling_settings


EXPECTED_DURATIONS = {
    "corte-social": 30,
    "corte-degrade": 30,
    "corte-militar": 30,
    "barba-alinhamento": 30,
    "barboterapia": 30,
    "sobrancelha": 30,
    "pigmentacao-barba-cabelo": 90,
    "platinado-luzes": 90,
}


def test_all_carlos_personas_use_confirmed_location_and_never_ask_where() -> None:
    exact_reply = (
        "O atendimento é na O Original Barbershop, Av. Brasil Leste, 245 - "
        "Belo Horizonte, Monte Carmelo - MG, 38500-000."
    )
    for prompt in (
        CARLOS_SYSTEM_PROMPT,
        CARLOS_SCHEDULING_SYSTEM_PROMPT,
        CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT,
    ):
        assert exact_reply in prompt
        assert "Nunca pergunte onde sera o atendimento" in prompt
        assert "nunca sugira encontro ou atendimento" in prompt


@pytest.mark.anyio
async def test_confirmed_seed_creates_eight_services_with_configured_durations(session_maker):
    async with session_maker() as session:
        await seed_confirmed_services(session)
        await seed_confirmed_services(session)
        await session.commit()
        services = list((await session.execute(select(Service))).scalars().all())

    by_slug = {service.slug: service for service in services}
    assert len(services) == 8
    assert {slug: by_slug[slug].duration_minutes for slug in EXPECTED_DURATIONS} == EXPECTED_DURATIONS
    assert sum(1 for service in services if service.duration_minutes == 30) == 6
    assert sum(1 for service in services if service.duration_minutes == 90) == 2
    assert all(service.active for service in services)
    assert by_slug["corte-social"].price_cents == 3000
    assert by_slug["platinado-luzes"].price_cents == 15000
    assert by_slug["pigmentacao-barba-cabelo"].price_cents == 1500


def test_seed_configuration_is_ready_for_scheduling_without_payment_warning(capsys):
    seed = load_seed_file()
    result = check_seed_configuration(seed)

    assert result["ready_for_information"] is True
    assert result["ready_for_scheduling"] is True
    assert result["errors"] == []
    assert [warning["code"] for warning in result["warnings"]] == [
        "promotion_configuration_incomplete",
    ]
    assert seed["address"]["city"] == "Monte Carmelo"
    assert seed["address"]["state"] == "MG"
    assert "address_incomplete" not in str(result)
    assert "service_durations_missing" not in str(result)
    assert "payment_methods_unconfirmed" not in str(result)
    assert len(seed["payment_methods"]) == 4
    assert len({method["key"] for method in seed["payment_methods"]}) == 4

    assert check_configuration_main([]) == 0
    output = capsys.readouterr().out
    assert "ready_for_scheduling: true" in output
    assert "payment_methods_unconfirmed" not in output


@pytest.mark.anyio
async def test_confirmed_seed_creates_real_business_hours_idempotently(session_maker):
    async with session_maker() as session:
        await seed_confirmed_barbershop(session, instance="o-original-barbershop")
        await seed_confirmed_barbershop(session, instance="o-original-barbershop")
        await session.commit()
        hours = list((await session.execute(select(BusinessHours))).scalars().all())

    active = sorted(
        (record.weekday, record.opens_at.strftime("%H:%M"), record.closes_at.strftime("%H:%M"))
        for record in hours
        if record.active and record.resource_key == "main"
    )
    assert active == [
        (1, "10:00", "20:00"),
        (2, "10:00", "20:00"),
        (3, "10:00", "20:00"),
        (4, "08:00", "20:00"),
        (5, "08:00", "16:00"),
    ]


@pytest.mark.anyio
async def test_list_services_and_barbershop_info_return_confirmed_public_data(session_maker):
    await _seed_catalog_and_hours(session_maker)
    executor = _read_executor(session_maker)
    message = _inbound("read-info")

    services_result = await executor.execute(
        tool_name=LIST_SERVICES_TOOL_NAME,
        arguments_json="{}",
        message=message,
    )
    info_result = await executor.execute(
        tool_name=GET_BARBERSHOP_INFO_TOOL_NAME,
        arguments_json="{}",
        message=message,
    )

    services = {service["slug"]: service for service in services_result.data["services"]}
    assert {slug: services[slug]["duration_minutes"] for slug in EXPECTED_DURATIONS} == EXPECTED_DURATIONS
    assert all(services[slug]["duration_configured"] is True for slug in EXPECTED_DURATIONS)
    assert all(services[slug]["booking_enabled"] is True for slug in EXPECTED_DURATIONS)
    assert services["corte-degrade"]["price_type"] == "fixed"
    assert services["corte-degrade"]["price_cents"] == 4000
    assert services["corte-degrade"]["price_display"] == "R$ 40,00"
    assert services["platinado-luzes"]["price_type"] == "starting_at"
    assert services["platinado-luzes"]["price_display"] == "A partir de R$ 150,00"
    assert services["platinado-luzes"]["requires_quote"] is True
    assert services["pigmentacao-barba-cabelo"]["price_type"] == "per_unit"
    assert "por area" in services["pigmentacao-barba-cabelo"]["price_display"]

    assert info_result.data == {
        "public_name": "O Original Barbershop",
        "address": (
            "O Original Barbershop, Av. Brasil Leste, 245 - Belo Horizonte, "
            "Monte Carmelo - MG, 38500-000."
        ),
        "city": "Monte Carmelo",
        "state": "MG",
        "postal_code": "38500-000",
        "google_maps_url": "https://maps.app.goo.gl/YqSBdh78FYGhJ6vg6",
        "payment_methods_configured": True,
        "payment_methods": ["Dinheiro", "Cartão de crédito", "Cartão de débito", "PIX"],
        "payment_information": "Aceitamos dinheiro, cartão de crédito, cartão de débito e PIX.",
        "barbers": [
            {"resource_key": "main", "display_name": "Lucas"},
            {"resource_key": "daniel", "display_name": "Daniel"},
        ],
    }
    assert "Todas a cima" not in info_result.model_dump_json()


@pytest.mark.anyio
async def test_all_eight_services_can_check_availability_and_prepare(session_maker):
    await _seed_catalog_and_hours(session_maker)
    read_executor = _read_executor(session_maker)
    action_service = _action_service(session_maker)
    message = _inbound("prepare-all")
    async with session_maker() as session:
        session.add(message)
        await session.commit()
        services = list((await session.execute(select(Service))).scalars().all())

    for service in services:
        slots = await read_executor.execute(
            tool_name=LIST_AVAILABLE_SLOTS_TOOL_NAME,
            arguments_json=f'{{"local_date": "2026-07-10", "service_ids": ["{service.id}"]}}',
            message=message,
        )
        prepared = await action_service.prepare_create(
            message=message,
            payload=_create_payload(service.id, time(8, 0)),
        )
        assert slots.ok is True
        assert slots.data["total_duration_minutes"] == EXPECTED_DURATIONS[service.slug]
        assert prepared.summary["total_duration_minutes"] == EXPECTED_DURATIONS[service.slug]


@pytest.mark.anyio
async def test_degrade_end_to_end_tool_flow_creates_one_thirty_minute_appointment(session_maker):
    await _seed_catalog_and_hours(session_maker)
    async with session_maker() as session:
        degrade = (await session.execute(select(Service).where(Service.slug == "corte-degrade"))).scalar_one()
        prepare = _inbound("prepare-degrade", text="Quero marcar um degradê amanhã às 14h.")
        confirm = _inbound("confirm-degrade", text="Sim, pode marcar.")
        session.add_all([prepare, confirm])
        await session.commit()

    executor = _write_executor(session_maker)
    listed = await executor.execute(tool_name=LIST_SERVICES_TOOL_NAME, arguments_json="{}", message=prepare)
    slots = await executor.execute(
        tool_name=LIST_AVAILABLE_SLOTS_TOOL_NAME,
        arguments_json=f'{{"local_date": "2026-07-10", "service_ids": ["{degrade.id}"]}}',
        message=prepare,
    )
    prepared = await executor.execute(
        tool_name=PREPARE_CREATE_APPOINTMENT_TOOL_NAME,
        arguments_json=(
            f'{{"service_ids": ["{degrade.id}"], "local_date": "2026-07-10", '
                '"local_start_time": "14:00", "customer_name": null, "barber": "lucas"}'
        ),
        message=prepare,
    )
    confirmed = await executor.execute(tool_name=CONFIRM_PENDING_ACTION_TOOL_NAME, arguments_json="{}", message=confirm)

    async with session_maker() as session:
        appointments = list((await session.execute(select(Appointment))).scalars().all())

    assert listed.ok is True
    assert slots.ok is True
    assert prepared.ok is True
    assert prepared.data["summary"]["total_duration_minutes"] == 30
    assert prepared.data["summary"]["total_price_cents"] == 4000
    assert confirmed.ok is True
    assert len(appointments) == 1
    assert appointments[0].total_duration_minutes == 30


@pytest.mark.anyio
async def test_platinado_and_pigmentacao_use_ninety_minutes_and_special_price_rules(session_maker):
    await _seed_catalog_and_hours(session_maker)
    async with session_maker() as session:
        platinado = (await session.execute(select(Service).where(Service.slug == "platinado-luzes"))).scalar_one()
        pigmentacao = (await session.execute(select(Service).where(Service.slug == "pigmentacao-barba-cabelo"))).scalar_one()
        inbound = _inbound("prepare-special")
        session.add(inbound)
        await session.commit()

    action_service = _action_service(session_maker)
    platinado_action = await action_service.prepare_create(
        message=inbound,
        payload=_create_payload(platinado.id, time(8, 0)),
    )
    pigmentacao_action = await action_service.prepare_create(
        message=inbound,
        payload=_create_payload(pigmentacao.id, time(10, 0)),
    )

    assert platinado_action.summary["total_duration_minutes"] == 90
    assert platinado_action.summary["total_price_cents"] == 15000
    assert platinado_action.summary["total_price_is_estimate"] is True
    assert pigmentacao_action.summary["total_duration_minutes"] == 90
    assert pigmentacao_action.summary["total_price_cents"] == 1500
    assert "total_price_is_estimate" not in pigmentacao_action.summary


def test_combo_and_prompt_rules_are_confirmed_without_invented_conditions():
    seed = load_seed_file()
    services = {service["slug"]: service for service in seed["services"]}
    combo_duration = (
        services["corte-social"]["duration_minutes"]
        + services["barba-alinhamento"]["duration_minutes"]
        + services["sobrancelha"]["duration_minutes"]
    )

    assert combo_duration == 90
    assert seed["promotion"]["estimated_duration_minutes"] == 90
    assert seed["promotion"]["booking_enabled"] is False
    assert "parcelamento" in CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT
    assert "bandeiras" in CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT
    assert "descontos" in CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT
    assert "a partir de R$ 150,00" in CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT
    assert "final depende de avaliacao" in CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT
    assert "R$ 15,00 por area" in CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT
    assert "barba ou cabelo" in CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT


async def _seed_catalog_and_hours(session_maker) -> None:
    async with session_maker() as session:
        await seed_confirmed_barbershop(session, instance="turatti")
        await session.commit()


def _read_executor(session_maker) -> SchedulingToolExecutor:
    return SchedulingToolExecutor(
        session_factory=session_maker,
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )


def _write_executor(session_maker) -> SchedulingWriteToolExecutor:
    settings = scheduling_settings()
    clock = FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC))
    return SchedulingWriteToolExecutor(
        read_executor=SchedulingToolExecutor(session_factory=session_maker, settings=settings, clock=clock),
        action_service=SchedulingActionService(session_factory=session_maker, settings=settings, clock=clock),
    )


def _action_service(session_maker) -> SchedulingActionService:
    return SchedulingActionService(
        session_factory=session_maker,
        settings=scheduling_settings(),
        clock=FakeClock(datetime(2026, 7, 10, 6, 0, tzinfo=UTC)),
    )


def _create_payload(service_id: str, local_start_time: time):
    from app.schemas.scheduling_action import CreateAppointmentActionPayload

    return CreateAppointmentActionPayload(
        service_ids=[service_id],
        local_date=date(2026, 7, 10),
        local_start_time=local_start_time,
        customer_name=None,
    )


def _inbound(message_id: str, *, text: str = "texto") -> InboundMessage:
    return InboundMessage(
        id=message_id,
        instance="turatti",
        message_id=message_id,
        phone="5534999999999",
        message_type="text",
        text=text,
        created_at=datetime(2026, 7, 10, 6, 0, tzinfo=UTC),
    )
