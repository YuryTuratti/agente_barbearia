import logging
import secrets
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse

from app.core.config import Settings, get_settings
from app.database.connection import get_database_session
from app.schemas.admin_dashboard import (
    AppointmentsResponse,
    BarbershopSettingsResponse,
    BusyHourItem,
    BusyHoursResponse,
    CancellationsResponse,
    ClientsResponse,
    DashboardSummary,
    MonthComparison,
    RevenueResponse,
    ServicesRanking,
)
from app.services.admin_dashboard_service import AdminDashboardService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic(auto_error=False)


def _require_admin_enabled(settings: Settings) -> None:
    if not settings.admin_dashboard_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


def require_admin_auth(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(security)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Settings:
    _require_admin_enabled(settings)
    if (
        settings.admin_dashboard_username is None
        or settings.admin_dashboard_password is None
        or credentials is None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Basic"},
        )

    password = settings.admin_dashboard_password.get_secret_value()
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.admin_dashboard_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        password.encode("utf-8"),
    )
    if not (username_ok and password_ok):
        logger.warning(
            "Admin dashboard authentication failed: endpoint=%s request_id=%s",
            request.url.path,
            getattr(request.state, "request_id", None),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Basic"},
        )

    logger.info(
        "Admin dashboard access: endpoint=%s request_id=%s",
        request.url.path,
        getattr(request.state, "request_id", None),
    )
    return settings


ADMIN_PAGES = {
    "dashboard": ("Visão geral", "/admin/dashboard"),
    "agenda": ("Agenda", "/admin/agenda"),
    "servicos": ("Serviços", "/admin/servicos"),
    "faturamento": ("Faturamento", "/admin/faturamento"),
    "clientes": ("Clientes", "/admin/clientes"),
    "horarios": ("Horários movimentados", "/admin/horarios"),
    "cancelamentos": ("Cancelamentos", "/admin/cancelamentos"),
    "configuracoes": ("Configurações", "/admin/configuracoes"),
}


def get_admin_dashboard_service(
    settings: Annotated[Settings, Depends(require_admin_auth)],
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> AdminDashboardService:
    return AdminDashboardService(session, settings=settings)


def _render_admin_page(*, active_page: str, settings: Settings) -> HTMLResponse:
    base_dir = Path(__file__).resolve().parents[1]
    template_dir = base_dir / "templates" / "admin"
    base = (template_dir / "base.html").read_text(encoding="utf-8")
    content = (template_dir / f"{active_page}.html").read_text(encoding="utf-8")
    css = (base_dir / "static" / "admin.css").read_text(encoding="utf-8")
    nav = "\n".join(
        (
            f'<a class="nav-link {"active" if page == active_page else ""}" '
            f'href="{href}" data-page="{page}">{label}</a>'
        )
        for page, (label, href) in ADMIN_PAGES.items()
    )
    html = (
        base.replace("{{ admin_css }}", css)
        .replace("{{ page_title }}", ADMIN_PAGES[active_page][0])
        .replace("{{ barbershop_timezone }}", settings.barbershop_timezone)
        .replace("{{ admin_nav }}", nav)
        .replace("{{ admin_content }}", content)
    )
    return HTMLResponse(html)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    settings: Annotated[Settings, Depends(require_admin_auth)],
) -> HTMLResponse:
    return _render_admin_page(active_page="dashboard", settings=settings)


@router.get("/agenda", response_class=HTMLResponse)
async def agenda_page(
    settings: Annotated[Settings, Depends(require_admin_auth)],
) -> HTMLResponse:
    return _render_admin_page(active_page="agenda", settings=settings)


@router.get("/servicos", response_class=HTMLResponse)
async def servicos_page(
    settings: Annotated[Settings, Depends(require_admin_auth)],
) -> HTMLResponse:
    return _render_admin_page(active_page="servicos", settings=settings)


@router.get("/faturamento", response_class=HTMLResponse)
async def faturamento_page(
    settings: Annotated[Settings, Depends(require_admin_auth)],
) -> HTMLResponse:
    return _render_admin_page(active_page="faturamento", settings=settings)


@router.get("/clientes", response_class=HTMLResponse)
async def clientes_page(
    settings: Annotated[Settings, Depends(require_admin_auth)],
) -> HTMLResponse:
    return _render_admin_page(active_page="clientes", settings=settings)


@router.get("/horarios", response_class=HTMLResponse)
async def horarios_page(
    settings: Annotated[Settings, Depends(require_admin_auth)],
) -> HTMLResponse:
    return _render_admin_page(active_page="horarios", settings=settings)


@router.get("/cancelamentos", response_class=HTMLResponse)
async def cancelamentos_page(
    settings: Annotated[Settings, Depends(require_admin_auth)],
) -> HTMLResponse:
    return _render_admin_page(active_page="cancelamentos", settings=settings)


@router.get("/configuracoes", response_class=HTMLResponse)
async def configuracoes_page(
    settings: Annotated[Settings, Depends(require_admin_auth)],
) -> HTMLResponse:
    return _render_admin_page(active_page="configuracoes", settings=settings)


@router.get("/api/dashboard-summary")
async def dashboard_summary(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
) -> DashboardSummary:
    return await service.dashboard_summary()


@router.get("/api/appointments")
async def appointments(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
    appointment_date: Annotated[date | None, Query(alias="date")] = None,
    status_filter: Annotated[str, Query(alias="status")] = "scheduled",
    resource_key: str = "all",
) -> AppointmentsResponse:
    service.resource_key = resource_key if resource_key in {"all", "main", "daniel"} else "all"
    return await service.appointments(local_date=appointment_date, status=status_filter)


@router.get("/api/services-ranking")
async def services_ranking(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
    period: str = "current_month",
    limit: int = 10,
    resource_key: str = "all",
) -> ServicesRanking:
    service.resource_key = resource_key if resource_key in {"all", "main", "daniel"} else "all"
    return await service.services_ranking(period=period, limit=limit)


@router.get("/api/month-comparison")
async def month_comparison(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
    resource_key: str = "all",
) -> MonthComparison:
    service.resource_key = resource_key if resource_key in {"all", "main", "daniel"} else "all"
    return await service.month_comparison()


@router.get("/api/busy-hours")
async def busy_hours(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
    resource_key: str = "all",
) -> list[BusyHourItem]:
    service.resource_key = resource_key if resource_key in {"all", "main", "daniel"} else "all"
    return await service.busy_hours()


@router.get("/api/busy-hours-detail")
async def busy_hours_detail(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
    resource_key: str = "all",
) -> BusyHoursResponse:
    service.resource_key = resource_key if resource_key in {"all", "main", "daniel"} else "all"
    return await service.busy_hours_detail()


@router.get("/api/revenue")
async def revenue(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
    resource_key: str = "all",
) -> RevenueResponse:
    service.resource_key = resource_key if resource_key in {"all", "main", "daniel"} else "all"
    return await service.revenue()


@router.get("/api/clients")
async def clients(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
    resource_key: str = "all",
) -> ClientsResponse:
    service.resource_key = resource_key if resource_key in {"all", "main", "daniel"} else "all"
    return await service.clients()


@router.get("/api/cancellations")
async def cancellations(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
    resource_key: str = "all",
) -> CancellationsResponse:
    service.resource_key = resource_key if resource_key in {"all", "main", "daniel"} else "all"
    return await service.cancellations()


@router.get("/api/barbershop-settings")
async def barbershop_settings(
    service: Annotated[AdminDashboardService, Depends(get_admin_dashboard_service)],
) -> BarbershopSettingsResponse:
    return service.barbershop_settings()
