import argparse
import asyncio
import json
import logging
from typing import Any

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.connection import AsyncSessionLocal, engine
from app.domain.barbershop_catalog import (
    BUSINESS_HOURS_CATALOG,
    BUSINESS_HOURS_BY_RESOURCE,
    RESOURCE_CATALOG,
    SERVICE_CATALOG,
    check_seed_configuration,
    load_seed_file,
    seed_confirmed_barbershop,
)

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed confirmed barbershop data.")
    parser.add_argument("--instance", required=True, help="Logical barbershop instance.")
    parser.add_argument("--file", default="data/barbershops/o_original_barbershop.json", help="Seed JSON path.")
    parser.add_argument("--resource-key", default=None, help="Agenda resource key.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview without writing.")
    parser.add_argument("--update-existing", action="store_true", help="Update existing services and business hours.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


async def run_seed(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    seed = load_seed_file(args.file)
    configuration = check_seed_configuration(seed)
    if configuration["errors"]:
        return {
            "ok": False,
            "dry_run": args.dry_run,
            "errors": configuration["errors"],
            "warnings": configuration["warnings"],
        }

    summary: dict[str, Any] = {
        "ok": True,
        "dry_run": args.dry_run,
        "instance": args.instance,
        "resource_key": args.resource_key or settings.default_resource_key,
        "services_expected": len(SERVICE_CATALOG),
        "resources_expected": len(RESOURCE_CATALOG),
        "business_hours_expected": sum(len(items) for items in BUSINESS_HOURS_BY_RESOURCE.values()),
        "warnings": configuration["warnings"],
    }
    if args.dry_run:
        return summary

    async with AsyncSessionLocal() as session:
        counts = await seed_confirmed_barbershop(
            session,
            instance=args.instance,
            resource_key=args.resource_key or settings.default_resource_key,
            update_existing=args.update_existing,
        )
        await session.commit()
    summary.update(counts)
    return summary


def format_text(summary: dict[str, Any]) -> str:
    lines = [
        "Barbershop seed",
        f"ok: {str(summary['ok']).lower()}",
        f"dry_run: {str(summary['dry_run']).lower()}",
    ]
    if "instance" in summary:
        lines.append(f"instance: {summary['instance']}")
    if "resource_key" in summary:
        lines.append(f"resource_key: {summary['resource_key']}")
    for key in (
        "services_expected",
        "services_created",
        "services_updated",
        "services_unchanged",
        "resources_expected",
        "resources_created",
        "resources_updated",
        "resources_unchanged",
        "business_hours_expected",
        "business_hours_created",
        "business_hours_updated",
        "business_hours_unchanged",
    ):
        if key in summary:
            lines.append(f"{key}: {summary[key]}")
    for warning in summary.get("warnings", []):
        lines.append(f"warning: {warning['code']} - {warning['message']}")
    for error in summary.get("errors", []):
        lines.append(f"error: {error['code']} - {error['message']}")
    return "\n".join(lines)


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings)
    try:
        summary = await run_seed(args)
    except Exception as error:
        logger.error("Barbershop seed failed: error_type=%s", error.__class__.__name__)
        return 1
    finally:
        await engine.dispose()
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    else:
        print(format_text(summary))
    return 0 if summary["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
