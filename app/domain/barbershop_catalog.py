from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BarbershopResource, BusinessHours, Service


SEED_PATH = Path("data/barbershops/o_original_barbershop.json")

PAYMENT_METHODS = [
    {"key": "cash", "display_name": "Dinheiro"},
    {"key": "credit_card", "display_name": "Cartão de crédito"},
    {"key": "debit_card", "display_name": "Cartão de débito"},
    {"key": "pix", "display_name": "PIX"},
]
PAYMENT_INFORMATION = "Aceitamos dinheiro, cartão de crédito, cartão de débito e PIX."


@dataclass(frozen=True)
class ServiceCatalogItem:
    slug: str
    name: str
    duration_minutes: int
    price_cents: int
    booking_enabled: bool = True
    price_type: str = "fixed"
    requires_quote: bool = False
    description: str | None = None


@dataclass(frozen=True)
class BusinessHoursCatalogItem:
    weekday: int
    opens_at: str
    closes_at: str


SERVICE_CATALOG = [
    ServiceCatalogItem("corte-social", "Corte Social", 30, 3000),
    ServiceCatalogItem("corte-degrade", "Corte Degradê", 30, 4000),
    ServiceCatalogItem("corte-militar", "Corte Militar", 30, 3000),
    ServiceCatalogItem("barba-alinhamento", "Barba - Alinhamento", 30, 2000),
    ServiceCatalogItem("barboterapia", "Barba Completa com Toalha Quente / Barboterapia", 30, 3500),
    ServiceCatalogItem("sobrancelha", "Sobrancelha", 30, 1000),
    ServiceCatalogItem(
        "pigmentacao-barba-cabelo",
        "Pigmentação de Barba ou Cabelo",
        90,
        1500,
        price_type="per_unit",
    ),
    ServiceCatalogItem(
        "platinado-luzes",
        "Platinado / Luzes",
        90,
        15000,
        price_type="starting_at",
        requires_quote=True,
    ),
]
SERVICE_CATALOG_BY_SLUG = {item.slug: item for item in SERVICE_CATALOG}

BUSINESS_HOURS_CATALOG = [
    BusinessHoursCatalogItem(1, "10:00", "20:00"),
    BusinessHoursCatalogItem(2, "10:00", "20:00"),
    BusinessHoursCatalogItem(3, "10:00", "20:00"),
    BusinessHoursCatalogItem(4, "08:00", "20:00"),
    BusinessHoursCatalogItem(5, "08:00", "16:00"),
]

RESOURCE_CATALOG = [
    {"resource_key": "main", "display_name": "Lucas", "is_active": True, "booking_enabled": True, "sort_order": 1},
    {"resource_key": "daniel", "display_name": "Daniel", "is_active": True, "booking_enabled": True, "sort_order": 2},
]
DANIEL_BUSINESS_HOURS_CATALOG = [
    BusinessHoursCatalogItem(day, opens, closes)
    for day, opens, closes in (
        (0, "09:00", "12:00"), (0, "13:00", "20:00"),
        (2, "09:00", "12:00"), (2, "13:00", "20:00"),
        (3, "09:00", "12:00"), (3, "13:00", "20:00"),
        (4, "09:00", "12:00"), (4, "13:00", "20:00"),
        (5, "09:00", "12:00"), (5, "13:00", "18:00"),
    )
]
BUSINESS_HOURS_BY_RESOURCE = {"main": BUSINESS_HOURS_CATALOG, "daniel": DANIEL_BUSINESS_HOURS_CATALOG}

PROMOTION = {
    "name": "Corte + Barba + Sobrancelha",
    "price_cents": 6000,
    "estimated_duration_minutes": 90,
    "booking_enabled": False,
    "pending_note": "O combo ainda precisa ter as modalidades de corte confirmadas.",
}


def get_service_catalog_item(slug: str) -> ServiceCatalogItem | None:
    return SERVICE_CATALOG_BY_SLUG.get(slug)


def service_price_type(slug: str) -> str:
    item = get_service_catalog_item(slug)
    return item.price_type if item is not None else "fixed"


def service_requires_quote(slug: str) -> bool:
    item = get_service_catalog_item(slug)
    return bool(item.requires_quote) if item is not None else False


def is_total_price_estimate(slugs: list[str]) -> bool:
    return any(service_requires_quote(slug) or service_price_type(slug) == "starting_at" for slug in slugs)


def format_price_display(*, slug: str, price_cents: int) -> str:
    price = format_brl(price_cents)
    price_type = service_price_type(slug)
    if price_type == "starting_at":
        return f"A partir de {price}"
    if price_type == "per_unit":
        return f"{price} por area"
    return price


def format_brl(price_cents: int) -> str:
    reais, cents = divmod(price_cents, 100)
    return f"R$ {reais},{cents:02d}"


def get_barbershop_info() -> dict[str, Any]:
    return {
        "payment_methods_configured": True,
        "payment_methods": [method["display_name"] for method in PAYMENT_METHODS],
        "payment_information": PAYMENT_INFORMATION,
        "barbers": [{"resource_key": item["resource_key"], "display_name": item["display_name"]} for item in RESOURCE_CATALOG],
    }


async def seed_confirmed_barbershop(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str = "main",
    update_existing: bool = False,
) -> dict[str, int]:
    service_counts = await seed_confirmed_services(
        session,
        update_existing=update_existing,
    )
    resource_counts = await seed_confirmed_resources(session, instance=instance, update_existing=update_existing)
    hours_counts = {"business_hours_created": 0, "business_hours_updated": 0, "business_hours_unchanged": 0}
    for key in BUSINESS_HOURS_BY_RESOURCE:
        counts = await seed_confirmed_business_hours(session, instance=instance, resource_key=key, update_existing=update_existing)
        for name, count in counts.items(): hours_counts[name] += count
    return {
        **service_counts,
        **resource_counts,
        **hours_counts,
    }


async def seed_confirmed_resources(session: AsyncSession, *, instance: str, update_existing: bool = True) -> dict[str, int]:
    created = updated = unchanged = 0
    result = await session.execute(select(BarbershopResource).where(BarbershopResource.instance == instance))
    existing = {item.resource_key: item for item in result.scalars().all()}
    for desired in RESOURCE_CATALOG:
        record = existing.get(desired["resource_key"])
        if record is None:
            session.add(BarbershopResource(instance=instance, **desired)); created += 1; continue
        before = (record.display_name, record.is_active, record.booking_enabled, record.sort_order)
        if update_existing:
            record.display_name = desired["display_name"]; record.is_active = desired["is_active"]
            record.booking_enabled = desired["booking_enabled"]; record.sort_order = desired["sort_order"]
        after = (record.display_name, record.is_active, record.booking_enabled, record.sort_order)
        updated += before != after; unchanged += before == after
    await session.flush()
    return {"resources_created": created, "resources_updated": updated, "resources_unchanged": unchanged}


async def seed_confirmed_services(
    session: AsyncSession,
    *,
    update_existing: bool = True,
) -> dict[str, int]:
    created = 0
    updated = 0
    unchanged = 0
    for item in SERVICE_CATALOG:
        result = await session.execute(select(Service).where(Service.slug == item.slug))
        service = result.scalar_one_or_none()
        if service is None:
            session.add(
                Service(
                    slug=item.slug,
                    name=item.name,
                    description=item.description,
                    duration_minutes=item.duration_minutes,
                    price_cents=item.price_cents,
                    active=True,
                )
            )
            created += 1
            continue
        if not update_existing:
            unchanged += 1
            continue
        before = (
            service.name,
            service.description,
            service.duration_minutes,
            service.price_cents,
            service.active,
        )
        service.name = item.name
        service.description = item.description
        service.duration_minutes = item.duration_minutes
        service.price_cents = item.price_cents
        service.active = True
        after = (
            service.name,
            service.description,
            service.duration_minutes,
            service.price_cents,
            service.active,
        )
        if before == after:
            unchanged += 1
        else:
            updated += 1
    await session.flush()
    return {
        "services_created": created,
        "services_updated": updated,
        "services_unchanged": unchanged,
    }


async def seed_confirmed_business_hours(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str = "main",
    update_existing: bool = True,
) -> dict[str, int]:
    from datetime import time

    created = 0
    updated = 0
    unchanged = 0
    catalog = BUSINESS_HOURS_BY_RESOURCE.get(resource_key, BUSINESS_HOURS_CATALOG)
    desired = {
        (item.weekday, time.fromisoformat(item.opens_at), time.fromisoformat(item.closes_at))
        for item in catalog
    }
    result = await session.execute(
        select(BusinessHours).where(
            BusinessHours.instance == instance,
            BusinessHours.resource_key == resource_key,
        )
    )
    existing = list(result.scalars().all())
    by_interval = {
        (record.weekday, record.opens_at, record.closes_at): record
        for record in existing
    }

    for interval in desired:
        record = by_interval.get(interval)
        if record is None:
            weekday, opens_at, closes_at = interval
            session.add(
                BusinessHours(
                    instance=instance,
                    resource_key=resource_key,
                    weekday=weekday,
                    opens_at=opens_at,
                    closes_at=closes_at,
                    active=True,
                )
            )
            created += 1
            continue
        if not update_existing:
            unchanged += 1
            continue
        if record.active:
            unchanged += 1
        else:
            record.active = True
            updated += 1

    if update_existing:
        for record in existing:
            interval = (record.weekday, record.opens_at, record.closes_at)
            if interval not in desired and record.active:
                record.active = False
                updated += 1

    await session.flush()
    return {
        "business_hours_created": created,
        "business_hours_updated": updated,
        "business_hours_unchanged": unchanged,
    }


def load_seed_file(path: str | Path | None = None) -> dict[str, Any]:
    seed_path = Path(path) if path is not None else SEED_PATH
    with seed_path.open(encoding="utf-8") as file:
        return json.load(file)


def check_seed_configuration(seed: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    resources = {item.get("resource_key"): item for item in seed.get("resources", [])}
    for desired in RESOURCE_CATALOG:
        resource = resources.get(desired["resource_key"])
        if resource is None:
            errors.append({"code": "resource_missing", "message": f"Profissional ausente: {desired['resource_key']}."})
        elif not resource.get("is_active") or not resource.get("booking_enabled"):
            errors.append({"code": "resource_unavailable", "message": f"Profissional indisponivel: {desired['resource_key']}."})
    daniel_hours = {(item.get("weekday"), item.get("opens_at"), item.get("closes_at")) for item in seed.get("resource_business_hours", {}).get("daniel", [])}
    expected_daniel = {(item.weekday, item.opens_at, item.closes_at) for item in DANIEL_BUSINESS_HOURS_CATALOG}
    if daniel_hours != expected_daniel:
        errors.append({"code": "daniel_business_hours_invalid", "message": "Horarios do Daniel diferem da configuracao."})

    if seed.get("payment_methods_configured") is not True:
        errors.append({"code": "payment_methods_unconfirmed", "message": "Formas de pagamento nao configuradas."})
    if seed.get("payment_methods") != PAYMENT_METHODS:
        errors.append({"code": "payment_methods_invalid", "message": "Formas de pagamento diferem da confirmacao."})
    if seed.get("payment_methods_pending_note") is not None:
        errors.append({"code": "payment_methods_pending_note_present", "message": "Pagamento nao deve ter pendencia."})

    services = {service.get("slug"): service for service in seed.get("services", [])}
    for item in SERVICE_CATALOG:
        service = services.get(item.slug)
        if service is None:
            errors.append({"code": "service_missing", "message": f"Servico ausente: {item.slug}."})
            continue
        if service.get("duration_minutes") != item.duration_minutes:
            errors.append({"code": "service_duration_invalid", "message": f"Duracao invalida para {item.slug}."})
        if service.get("booking_enabled") is not True:
            errors.append({"code": "service_booking_disabled", "message": f"Agendamento desabilitado para {item.slug}."})
        if service.get("active") is not True:
            errors.append({"code": "service_inactive", "message": f"Servico inativo: {item.slug}."})

    seed_hours = {
        (item.get("weekday"), item.get("opens_at"), item.get("closes_at"))
        for item in seed.get("business_hours", [])
    }
    expected_hours = {
        (item.weekday, item.opens_at, item.closes_at)
        for item in BUSINESS_HOURS_CATALOG
    }
    if seed_hours != expected_hours:
        errors.append({"code": "business_hours_invalid", "message": "Horarios do seed diferem da confirmacao."})

    promotion = seed.get("promotion", {})
    if promotion.get("booking_enabled") is not False:
        errors.append({"code": "promotion_booking_enabled", "message": "Combo nao deve estar agendavel ainda."})
    if promotion.get("estimated_duration_minutes") != 90:
        errors.append({"code": "promotion_duration_invalid", "message": "Duracao conceitual do combo deve ser 90 minutos."})
    warnings.append(
        {
            "code": "promotion_configuration_incomplete",
            "message": "O combo ainda precisa ter as modalidades de corte confirmadas.",
        }
    )

    address = seed.get("address", {})
    if not address.get("city") or not address.get("postal_code"):
        warnings.append(
            {
                "code": "address_incomplete",
                "message": "Cidade e CEP nao foram informados no formulario.",
            }
        )

    return {
        "ready_for_information": not errors,
        "ready_for_scheduling": not errors,
        "errors": errors,
        "warnings": warnings,
    }


async def check_database_configuration(
    session: AsyncSession,
    *,
    instance: str,
    resource_key: str = "main",
) -> dict[str, Any]:
    from datetime import time

    errors: list[dict[str, str]] = []
    resources_result = await session.execute(select(BarbershopResource).where(BarbershopResource.instance == instance))
    resources = {item.resource_key: item for item in resources_result.scalars().all()}
    for desired in RESOURCE_CATALOG:
        record = resources.get(desired["resource_key"])
        if record is None:
            errors.append({"code": "resource_missing_in_database", "message": f"Profissional ausente no banco: {desired['resource_key']}."})
        elif not record.is_active or not record.booking_enabled:
            errors.append({"code": "resource_unavailable_in_database", "message": f"Profissional indisponivel no banco: {desired['resource_key']}."})
    service_result = await session.execute(select(Service))
    services = {service.slug: service for service in service_result.scalars().all()}
    for item in SERVICE_CATALOG:
        service = services.get(item.slug)
        if service is None:
            errors.append({"code": "service_missing_in_database", "message": f"Servico ausente no banco: {item.slug}."})
            continue
        if service.duration_minutes != item.duration_minutes:
            errors.append({"code": "service_duration_invalid_in_database", "message": f"Duracao invalida no banco: {item.slug}."})
        if service.price_cents != item.price_cents:
            errors.append({"code": "service_price_invalid_in_database", "message": f"Preco invalido no banco: {item.slug}."})
        if not service.active:
            errors.append({"code": "service_inactive_in_database", "message": f"Servico inativo no banco: {item.slug}."})

    for key, catalog in BUSINESS_HOURS_BY_RESOURCE.items():
        hours_result = await session.execute(select(BusinessHours).where(BusinessHours.instance == instance, BusinessHours.resource_key == key, BusinessHours.active.is_(True)))
        active_hours = {(record.weekday, record.opens_at, record.closes_at) for record in hours_result.scalars().all()}
        expected_hours = {(item.weekday, time.fromisoformat(item.opens_at), time.fromisoformat(item.closes_at)) for item in catalog}
        if active_hours != expected_hours:
            errors.append({"code": "business_hours_invalid_in_database", "message": f"Horarios ativos de {key} diferem do seed confirmado."})

    return {
        "database_ready": not errors,
        "errors": errors,
    }
