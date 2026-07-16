import inspect
import logging
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.api import admin_dashboard
from app.core.config import Settings
from app.database.models import Appointment, AppointmentService, BusinessHours, Customer, Service
from app.domain.scheduling import get_timezone
from app.main import app
from app.services.admin_dashboard_service import AdminDashboardService, mask_phone


ADMIN_PASSWORD = "senha-forte-testes"


def admin_settings(**overrides) -> Settings:
    values = {
        "database_url": "sqlite+aiosqlite:///test.db",
        "admin_dashboard_enabled": True,
        "admin_dashboard_username": "admin",
        "admin_dashboard_password": SecretStr(ADMIN_PASSWORD),
        "barbershop_instance": "o-original-barbershop",
        "default_resource_key": "main",
        "barbershop_timezone": "America/Sao_Paulo",
    }
    values.update(overrides)
    return Settings(**values)


def auth(username: str = "admin", password: str = ADMIN_PASSWORD) -> tuple[str, str]:
    return username, password


def local_utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    zone = get_timezone("America/Sao_Paulo")
    return datetime(year, month, day, hour, minute, tzinfo=zone).astimezone(UTC)


async def add_dashboard_hours(session, *, weekday: int, opens_at=time(8), closes_at=time(18)):
    session.add(
        BusinessHours(
            instance="o-original-barbershop",
            resource_key="main",
            weekday=weekday,
            opens_at=opens_at,
            closes_at=closes_at,
            active=True,
        )
    )
    await session.commit()


async def add_dashboard_service(
    session,
    *,
    slug: str,
    name: str,
    duration_minutes: int = 30,
    price_cents: int = 4000,
) -> Service:
    service = Service(
        slug=slug,
        name=name,
        duration_minutes=duration_minutes,
        price_cents=price_cents,
        active=True,
    )
    session.add(service)
    await session.commit()
    return service


async def add_dashboard_customer(
    session,
    *,
    phone: str = "5534999999999",
    name: str | None = "Yury",
) -> Customer:
    customer = Customer(
        instance="o-original-barbershop",
        phone=phone,
        name=name,
    )
    session.add(customer)
    await session.commit()
    return customer


async def add_dashboard_appointment(
    session,
    *,
    customer: Customer,
    service: Service,
    starts_at: datetime,
    status: str = "scheduled",
    code: str,
    snapshot_name: str | None = None,
    snapshot_price: int | None = None,
    cancellation_reason: str | None = None,
) -> Appointment:
    appointment = Appointment(
        instance="o-original-barbershop",
        resource_key="main",
        customer_id=customer.id,
        confirmation_code=code,
        status=status,
        start_at=starts_at,
        end_at=starts_at + timedelta(minutes=service.duration_minutes),
        total_duration_minutes=service.duration_minutes,
        total_price_cents=service.price_cents if snapshot_price is None else snapshot_price,
        cancellation_reason=cancellation_reason,
    )
    session.add(appointment)
    await session.flush()
    session.add(
        AppointmentService(
            appointment_id=appointment.id,
            service_id=service.id,
            position=0,
            service_name_snapshot=snapshot_name or service.name,
            duration_minutes_snapshot=service.duration_minutes,
            price_cents_snapshot=service.price_cents if snapshot_price is None else snapshot_price,
        )
    )
    await session.commit()
    return appointment


async def seed_dashboard_data(session) -> dict[str, Service]:
    corte = await add_dashboard_service(
        session, slug="corte-degrade", name="Corte Degrade", price_cents=4000
    )
    barba = await add_dashboard_service(
        session, slug="barba-alinhamento", name="Barba", price_cents=2000
    )
    platinado = await add_dashboard_service(
        session,
        slug="platinado-luzes",
        name="Platinado / Luzes",
        duration_minutes=90,
        price_cents=15000,
    )
    yury = await add_dashboard_customer(session, phone="5534999999999", name="Yury")
    ana = await add_dashboard_customer(session, phone="5534888877777", name="Ana")
    await add_dashboard_hours(session, weekday=3, opens_at=time(8), closes_at=time(18))
    await add_dashboard_hours(session, weekday=4, opens_at=time(8), closes_at=time(18))
    await add_dashboard_appointment(
        session, customer=yury, service=corte, starts_at=local_utc(2026, 7, 9, 14), code="AAAA1111"
    )
    await add_dashboard_appointment(
        session, customer=ana, service=corte, starts_at=local_utc(2026, 7, 9, 14, 30), code="BBBB2222"
    )
    await add_dashboard_appointment(
        session,
        customer=ana,
        service=barba,
        starts_at=local_utc(2026, 7, 10, 15),
        status="completed",
        code="CCCC3333",
        snapshot_name="Barba Snapshot",
        snapshot_price=2500,
    )
    await add_dashboard_appointment(
        session,
        customer=yury,
        service=barba,
        starts_at=local_utc(2026, 7, 10, 16),
        status="cancelled",
        code="DDDD4444",
        cancellation_reason="Cliente pediu para remarcar\nsem novo horário.",
    )
    await add_dashboard_appointment(
        session, customer=yury, service=platinado, starts_at=local_utc(2026, 7, 11, 10), status="no_show", code="EEEE5555"
    )
    await add_dashboard_appointment(
        session, customer=yury, service=corte, starts_at=local_utc(2026, 6, 12, 10), code="FFFF6666"
    )
    return {"corte": corte, "barba": barba, "platinado": platinado}


def override_admin_settings(settings: Settings) -> None:
    app.dependency_overrides[admin_dashboard.get_settings] = lambda: settings


def test_admin_dashboard_disabled_by_default() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///test.db")

    assert settings.admin_dashboard_enabled is False


def test_admin_dashboard_requires_credentials_when_enabled() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="sqlite+aiosqlite:///test.db",
            admin_dashboard_enabled=True,
        )


def test_admin_dashboard_password_is_masked_in_repr() -> None:
    settings = admin_settings(admin_dashboard_password=SecretStr("segredo-admin"))

    assert "segredo-admin" not in repr(settings)


def test_env_production_example_has_admin_defaults_without_real_password() -> None:
    content = Path(".env.production.example").read_text(encoding="utf-8")

    assert "ADMIN_DASHBOARD_ENABLED=false" in content
    assert "ADMIN_DASHBOARD_USERNAME=CHANGE_ME" in content
    assert "ADMIN_DASHBOARD_PASSWORD=CHANGE_ME" in content
    assert "turatti57" not in content
    assert "F0BC4B59" not in content


def test_admin_disabled_returns_404(client: TestClient) -> None:
    override_admin_settings(admin_settings(admin_dashboard_enabled=False))

    response = client.get("/admin/dashboard")

    assert response.status_code == 404


def test_admin_auth_blocks_missing_and_invalid_credentials(client: TestClient) -> None:
    override_admin_settings(admin_settings())

    assert client.get("/admin/dashboard").status_code == 401
    assert client.get("/admin/dashboard", auth=auth("wrong", ADMIN_PASSWORD)).status_code == 401
    assert client.get("/admin/dashboard", auth=auth("admin", "wrong")).status_code == 401


def test_admin_auth_allows_correct_credentials_without_leaking_password(client: TestClient) -> None:
    override_admin_settings(admin_settings())

    response = client.get("/admin/dashboard", auth=auth())

    assert response.status_code == 200
    assert ADMIN_PASSWORD not in response.text


def test_admin_auth_uses_compare_digest_and_does_not_log_password(client: TestClient, caplog) -> None:
    override_admin_settings(admin_settings())

    assert "compare_digest" in inspect.getsource(admin_dashboard.require_admin_auth)
    with caplog.at_level(logging.WARNING):
        client.get("/admin/dashboard", auth=auth("admin", "wrong"))

    assert ADMIN_PASSWORD not in caplog.text
    assert "wrong" not in caplog.text


ADMIN_PAGE_ROUTES = [
    "/admin/dashboard",
    "/admin/agenda",
    "/admin/servicos",
    "/admin/faturamento",
    "/admin/clientes",
    "/admin/horarios",
    "/admin/cancelamentos",
    "/admin/configuracoes",
]


def test_all_admin_pages_require_authentication_and_work_authenticated(client: TestClient) -> None:
    override_admin_settings(admin_settings())

    for route in ADMIN_PAGE_ROUTES:
        assert client.get(route).status_code == 401
        assert client.get(route, auth=auth("admin", "wrong")).status_code == 401
        response = client.get(route, auth=auth())
        assert response.status_code == 200
        assert "Área do barbeiro" in response.text
        assert 'class="nav-link active"' in response.text


def test_all_admin_pages_return_404_when_disabled(client: TestClient) -> None:
    override_admin_settings(admin_settings(admin_dashboard_enabled=False))

    for route in ADMIN_PAGE_ROUTES:
        assert client.get(route, auth=auth()).status_code == 404


def test_dashboard_navigation_links_and_active_menu(client: TestClient) -> None:
    override_admin_settings(admin_settings())

    response = client.get("/admin/dashboard", auth=auth())

    assert response.status_code == 200
    for route in ADMIN_PAGE_ROUTES:
        assert f'href="{route}"' in response.text
    assert 'data-page="dashboard">Visão geral</a>' in response.text
    assert 'href="/admin/agenda"' in response.text
    assert 'href="/admin/servicos"' in response.text
    assert 'href="/admin/faturamento"' in response.text
    assert 'href="/admin/clientes"' in response.text
    assert 'href="/admin/horarios"' in response.text
    assert 'href="/admin/cancelamentos"' in response.text
    assert 'href="/admin/configuracoes"' in response.text


@pytest.mark.anyio
async def test_dashboard_summary_calculates_month_status_revenue_clients_timezone(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    summary = await service.dashboard_summary()

    assert summary.period.current_month == "2026-07"
    assert summary.period.previous_month == "2026-06"
    assert summary.appointments.scheduled_this_month == 5
    assert summary.appointments.scheduled_previous_month == 1
    assert summary.appointments.growth_percent == 400.0
    assert summary.appointments.completed_this_month == 1
    assert summary.appointments.cancelled_this_month == 1
    assert summary.appointments.no_show_this_month == 1
    assert summary.revenue.estimated_this_month_cents == 10500
    assert summary.revenue.estimated_previous_month_cents == 4000
    assert summary.revenue.growth_percent == 162.5
    assert summary.revenue.has_estimates is False
    assert summary.clients.unique_clients_this_month == 2


@pytest.mark.anyio
async def test_dashboard_summary_handles_zero_previous_month_and_occupancy(db_session):
    corte = await add_dashboard_service(
        db_session, slug="corte-degrade", name="Corte Degrade", price_cents=4000
    )
    customer = await add_dashboard_customer(db_session)
    await add_dashboard_hours(db_session, weekday=3, opens_at=time(8), closes_at=time(9))
    await add_dashboard_appointment(
        db_session, customer=customer, service=corte, starts_at=local_utc(2026, 7, 9, 8), code="ZERO1111"
    )
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    summary = await service.dashboard_summary()

    assert summary.appointments.growth_percent is None
    assert summary.revenue.growth_percent is None
    assert summary.occupancy.scheduled_minutes == 30
    assert summary.occupancy.available_minutes > 0
    assert summary.occupancy.occupancy_percent is not None


@pytest.mark.anyio
async def test_services_ranking_uses_snapshots_ignores_cancelled_orders_and_limits(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    ranking = await service.services_ranking(limit=1)

    assert len(ranking.most_booked) == 1
    assert ranking.most_booked[0].service_slug == "corte-degrade"
    assert ranking.most_booked[0].count == 2
    assert ranking.least_booked[0].service_name == "Barba Snapshot"
    assert ranking.least_booked[0].estimated_revenue_cents == 2500


@pytest.mark.anyio
async def test_services_ranking_works_without_data(db_session):
    service = AdminDashboardService(db_session, settings=admin_settings())

    ranking = await service.services_ranking()

    assert ranking.most_booked == []
    assert ranking.least_booked == []


@pytest.mark.anyio
async def test_appointments_accept_date_status_order_mask_phone_services_and_totals(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(db_session, settings=admin_settings())

    response = await service.appointments(local_date=date(2026, 7, 9), status="all")

    assert response.date == "2026-07-09"
    assert [item.start_time for item in response.appointments] == ["14:00", "14:30"]
    assert response.appointments[0].phone_masked == "55******9999"
    assert response.appointments[0].services[0].name == "Corte Degrade"
    assert response.appointments[0].total_price_cents == 4000
    assert not hasattr(response.appointments[0], "payload")


@pytest.mark.anyio
async def test_appointments_filters_status(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(db_session, settings=admin_settings())

    response = await service.appointments(local_date=date(2026, 7, 10), status="completed")

    assert len(response.appointments) == 1
    assert response.appointments[0].status == "completed"


@pytest.mark.anyio
async def test_busy_hours_groups_by_local_hour_orders_and_handles_empty(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    busy = await service.busy_hours()

    assert busy[0].hour == "14:00"
    assert busy[0].appointments == 2
    assert all(item.hour != "16:00" for item in busy)


@pytest.mark.anyio
async def test_busy_hours_detail_groups_weekdays_and_occupancy(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    detail = await service.busy_hours_detail()

    assert detail.hours[0].hour == "14:00"
    assert detail.weekdays[0].label == "Quinta"
    assert detail.occupancy.scheduled_minutes > 0
    assert detail.occupancy.available_minutes > 0


@pytest.mark.anyio
async def test_revenue_detail_estimates_difference_ticket_and_ignores_cancelled(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    revenue = await service.revenue()

    assert revenue.current_month.estimated_revenue_cents == 10500
    assert revenue.previous_month.estimated_revenue_cents == 4000
    assert revenue.difference.estimated_revenue_cents == 6500
    assert revenue.difference.estimated_revenue_percent == 162.5
    assert revenue.considered_appointments == 3
    assert revenue.ticket_average_cents == 3500
    assert "não valida pagamentos recebidos" in revenue.notice
    assert "confirmado" not in revenue.notice.lower()


@pytest.mark.anyio
async def test_clients_detail_recurring_order_masking_and_no_conversations(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    clients = await service.clients()

    assert clients.unique_clients_this_month == 2
    assert clients.unique_clients_previous_month == 1
    assert clients.recurring_clients == 2
    assert clients.top_clients[0].appointments >= clients.top_clients[1].appointments
    assert clients.top_clients[0].phone_masked == "55******9999"
    assert not hasattr(clients.top_clients[0], "conversation")
    assert not hasattr(clients.top_clients[0], "transcription")


@pytest.mark.anyio
async def test_cancellations_detail_counts_rate_reason_and_masks_phone(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    cancellations = await service.cancellations()

    assert cancellations.cancelled_this_month == 1
    assert cancellations.cancelled_previous_month == 0
    assert cancellations.no_show_this_month == 1
    assert cancellations.cancellation_rate_percent == 20.0
    cancelled = next(item for item in cancellations.recent if item.status == "cancelled")
    assert cancelled.reason == "Cliente pediu para remarcar sem novo horário."
    assert cancelled.phone_masked == "55******9999"


@pytest.mark.anyio
async def test_occupancy_handles_zero_available_minutes_and_ignores_cancelled(db_session):
    corte = await add_dashboard_service(
        db_session, slug="corte-degrade", name="Corte Degrade", price_cents=4000
    )
    customer = await add_dashboard_customer(db_session)
    await add_dashboard_appointment(
        db_session, customer=customer, service=corte, starts_at=local_utc(2026, 7, 9, 8), code="OCCU1111"
    )
    await add_dashboard_appointment(
        db_session, customer=customer, service=corte, starts_at=local_utc(2026, 7, 9, 9), status="cancelled", code="OCCU2222"
    )
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    summary = await service.dashboard_summary()

    assert summary.occupancy.scheduled_minutes == 30
    assert summary.occupancy.available_minutes == 0
    assert summary.occupancy.occupancy_percent is None


@pytest.mark.anyio
async def test_month_comparison_current_previous_difference(db_session):
    await seed_dashboard_data(db_session)
    service = AdminDashboardService(
        db_session,
        settings=admin_settings(),
        clock=type("Clock", (), {"now_utc": lambda self: local_utc(2026, 7, 9, 12)})(),
    )

    comparison = await service.month_comparison()

    assert comparison.current_month.label == "Julho/2026"
    assert comparison.previous_month.label == "Junho/2026"
    assert comparison.difference.appointments == 4
    assert comparison.difference.estimated_revenue_cents == 6500


@pytest.mark.anyio
async def test_admin_api_endpoints_and_html_privacy(client: TestClient, db_session):
    override_admin_settings(admin_settings())
    await seed_dashboard_data(db_session)

    summary = client.get("/admin/api/dashboard-summary", auth=auth())
    appointments = client.get("/admin/api/appointments?date=2026-07-09&status=all", auth=auth())
    ranking = client.get("/admin/api/services-ranking?limit=2", auth=auth())
    comparison = client.get("/admin/api/month-comparison", auth=auth())
    busy = client.get("/admin/api/busy-hours", auth=auth())
    busy_detail = client.get("/admin/api/busy-hours-detail", auth=auth())
    revenue = client.get("/admin/api/revenue", auth=auth())
    clients = client.get("/admin/api/clients", auth=auth())
    cancellations = client.get("/admin/api/cancellations", auth=auth())
    settings = client.get("/admin/api/barbershop-settings", auth=auth())
    html = client.get("/admin/dashboard", auth=auth())

    assert summary.status_code == 200
    assert appointments.status_code == 200
    assert ranking.status_code == 200
    assert comparison.status_code == 200
    assert busy.status_code == 200
    assert busy_detail.status_code == 200
    assert revenue.status_code == 200
    assert clients.status_code == 200
    assert cancellations.status_code == 200
    assert settings.status_code == 200
    assert html.status_code == 200
    assert "Agendamentos do mês" in html.text
    assert "Faturamento estimado" in html.text
    assert "5534999999999" not in appointments.text
    assert "5534999999999" not in clients.text
    assert "5534999999999" not in cancellations.text
    assert "5534999999999" not in html.text
    assert ADMIN_PASSWORD not in html.text
    assert "payload" not in appointments.text


def test_barbershop_settings_exposes_only_public_information() -> None:
    service = AdminDashboardService(
        session=None,  # type: ignore[arg-type]
        settings=admin_settings(),
    )

    payload = service.barbershop_settings()
    serialized = payload.model_dump_json()

    assert payload.public_name == "O Original Barbershop"
    assert "Avenida Braulino Martins Mundim" in (payload.address or "")
    assert payload.google_maps_url is not None
    assert payload.business_hours
    assert "PIX" in payload.payment_methods
    assert payload.services
    assert payload.promotion is not None
    assert "Cidade e CEP" in " ".join(payload.pending_items)
    assert "combo" in " ".join(payload.pending_items)
    assert "manager_name" not in serialized
    assert "DATABASE_URL" not in serialized
    assert "API_KEY" not in serialized
    assert "prompt" not in serialized.lower()


def test_admin_pages_do_not_include_secrets_phone_or_prompts(client: TestClient) -> None:
    override_admin_settings(admin_settings())

    for route in ADMIN_PAGE_ROUTES:
        response = client.get(route, auth=auth())
        assert response.status_code == 200
        assert ADMIN_PASSWORD not in response.text
        assert "DATABASE_URL" not in response.text
        assert "API_KEY" not in response.text
        assert "5534999999999" not in response.text
        assert "prompt" not in response.text.lower()
        assert "cdn" not in response.text.lower()
        assert "<style>" in response.text


def test_mask_phone() -> None:
    assert mask_phone("5534999999999") == "55******9999"
    assert mask_phone("12345") == "*****"


def test_dashboard_static_and_template_are_packaged_without_cdn() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    templates = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("app/templates/admin").glob("*.html")
    )

    assert "COPY --chown=app:app app ./app" in dockerfile
    assert Path("app/static/admin.css").exists()
    assert "cdn" not in templates.lower()
    assert "google-analytics" not in templates.lower()
