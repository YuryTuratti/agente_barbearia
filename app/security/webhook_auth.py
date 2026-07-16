import secrets

from fastapi import HTTPException, Request

from app.core.config import Settings, get_settings


def compare_webhook_secret(received: str, expected: str) -> bool:
    return secrets.compare_digest(received, expected)


async def verify_evolution_webhook_auth(
    request: Request,
) -> None:
    active_settings = get_settings()
    if not active_settings.evolution_webhook_auth_enabled:
        return
    expected_secret = active_settings.evolution_webhook_secret
    if expected_secret is None:
        raise HTTPException(status_code=403, detail="Webhook not authorized.")
    received_secret = request.headers.get(active_settings.evolution_webhook_secret_header)
    if received_secret is None:
        raise HTTPException(status_code=403, detail="Webhook not authorized.")
    if not compare_webhook_secret(received_secret, expected_secret.get_secret_value()):
        raise HTTPException(status_code=403, detail="Webhook not authorized.")
