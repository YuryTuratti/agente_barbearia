import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_dashboard import router as admin_dashboard_router
from app.api.evolution_webhook import router as evolution_webhook_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.connection import engine
from app.database.connection import get_database_session
from app.middleware.body_limit import WebhookBodyLimitMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.services.health_service import check_database_ready

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings)
    logger.info(
        "API starting: service=%s environment=%s version=%s",
        settings.app_name,
        settings.app_env,
        settings.app_build_version,
    )
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("API stopped safely.")


app = FastAPI(
    title=settings.app_name,
    description="Agente de IA para atendimento e agendamento via WhatsApp",
    version=settings.app_build_version,
    docs_url="/docs" if settings.app_enable_docs else None,
    redoc_url="/redoc" if settings.app_enable_docs else None,
    openapi_url="/openapi.json" if settings.app_enable_docs else None,
    lifespan=lifespan,
)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(WebhookBodyLimitMiddleware, settings=settings)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request,
    exc: RequestValidationError,
):
    if any(error.get("type") == "json_invalid" for error in exc.errors()):
        return JSONResponse(
            {"detail": "O corpo da requisição não contém um JSON válido."},
            status_code=400,
        )
    return await request_validation_exception_handler(request, exc)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Return the API health status."""
    return {
        "status": "online",
        "service": "Carlos - Turatti Barbe",
    }


@app.get("/health/live")
async def live_health_check() -> dict[str, str]:
    return {
        "status": "online",
        "service": "api",
    }


@app.get("/health/ready")
async def ready_health_check(
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, str]:
    try:
        await check_database_ready(session)
    except Exception as error:
        logger.error(
            "Readiness check failed: error_type=%s",
            error.__class__.__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Serviço temporariamente indisponível.",
        ) from error
    return {
        "status": "ready",
        "database": "connected",
        "migrations": "up_to_date",
    }


@app.get("/health/database")
async def database_health_check(
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, str]:
    """Return database connectivity status."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.error(
            "Database health check failed: error_type=%s",
            error.__class__.__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Serviço temporariamente indisponível.",
        ) from error

    return {
        "status": "online",
        "database": "connected",
    }


@app.get("/info")
async def info() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "environment": settings.app_env,
        "version": settings.app_build_version,
    }


app.include_router(evolution_webhook_router)
app.include_router(admin_dashboard_router)
