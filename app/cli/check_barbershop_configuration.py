import json
import argparse
import asyncio
import logging

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.connection import AsyncSessionLocal, engine
from app.domain.barbershop_catalog import (
    check_database_configuration,
    check_seed_configuration,
    load_seed_file,
)

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check confirmed barbershop configuration.")
    parser.add_argument("--instance", default=None, help="Logical barbershop instance.")
    parser.add_argument("--file", default="data/barbershops/o_original_barbershop.json", help="Seed JSON path.")
    parser.add_argument("--resource-key", default=None, help="Agenda resource key.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON output.")
    return parser.parse_args(argv)


async def collect_configuration(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    result = check_seed_configuration(load_seed_file(args.file))
    instance = args.instance or settings.barbershop_instance
    if args.instance is not None:
        async with AsyncSessionLocal() as session:
            database = await check_database_configuration(
                session,
                instance=instance,
                resource_key=args.resource_key or settings.default_resource_key,
            )
        result["database_ready"] = database["database_ready"]
        result["errors"] = [*result["errors"], *database["errors"]]
        result["ready_for_scheduling"] = result["ready_for_scheduling"] and database["database_ready"]
        result["ready_for_information"] = result["ready_for_information"] and database["database_ready"]
    result["instance"] = instance
    return result


def format_text(result: dict[str, object]) -> str:
    lines = [
        "Barbershop configuration",
        f"instance: {result['instance']}",
        f"ready_for_information: {str(result['ready_for_information']).lower()}",
        f"ready_for_scheduling: {str(result['ready_for_scheduling']).lower()}",
    ]
    if "database_ready" in result:
        lines.append(f"database_ready: {str(result['database_ready']).lower()}")
    for error in result["errors"]:
        lines.append(f"error: {error['code']} - {error['message']}")
    for warning in result["warnings"]:
        lines.append(f"warning: {warning['code']} - {warning['message']}")
    return "\n".join(lines)


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings)
    try:
        result = await collect_configuration(args)
    except Exception as error:
        logger.error("Barbershop configuration check failed: error_type=%s", error.__class__.__name__)
        return 1
    finally:
        await engine.dispose()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(format_text(result))
    return 0 if result["ready_for_information"] and result["ready_for_scheduling"] else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
