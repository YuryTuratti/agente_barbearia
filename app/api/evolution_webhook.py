import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import get_database_session
from app.repositories.inbound_message_repository import register_message
from app.repositories.inbound_media_repository import register_inbound_media
from app.security.webhook_auth import verify_evolution_webhook_auth
from app.services.message_normalizer import normalize_evolution_message

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/webhooks/evolution",
    tags=["Evolution API"],
    dependencies=[Depends(verify_evolution_webhook_auth)],
)


@router.post("")
async def receive_evolution_webhook(
    request: Request,
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, object]:
    """Receive webhook events sent by Evolution API."""
    try:
        parsed_payload = await request.json()
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="O corpo da requisição não contém um JSON válido.",
        ) from error

    if not isinstance(parsed_payload, dict):
        raise HTTPException(
            status_code=400,
            detail="O corpo da requisição não contém um JSON válido.",
        )

    payload: dict[str, object] = parsed_payload
    normalized_message = normalize_evolution_message(payload)
    duplicate = False
    accepted_for_processing = False

    if normalized_message.processable:
        try:
            registration_result = await register_message(
                session=session,
                message=normalized_message,
            )
            if normalized_message.media is not None:
                await register_inbound_media(
                    session=session,
                    inbound_message_id=registration_result.record_id,
                    media=normalized_message.media,
                )
        except SQLAlchemyError as error:
            logger.error(
                "Failed to register inbound message: event=%s message_type=%s "
                "error_type=%s",
                normalized_message.event,
                normalized_message.message_type,
                error.__class__.__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="Serviço temporariamente indisponível.",
            ) from error

        duplicate = registration_result.duplicate
        accepted_for_processing = registration_result.created

    logger.info(
        "Evolution webhook received: event=%s message_type=%s "
        "from_me=%s is_group=%s processable=%s "
        "ignore_reason=%s duplicate=%s accepted_for_processing=%s",
        normalized_message.event,
        normalized_message.message_type,
        normalized_message.from_me,
        normalized_message.is_group,
        normalized_message.processable,
        normalized_message.ignore_reason,
        duplicate,
        accepted_for_processing,
    )

    return {
        "received": True,
        "event": normalized_message.event,
        "instance": normalized_message.instance,
        "has_data": payload.get("data") is not None,
        "message": {
            "id": normalized_message.message_id,
            "type": normalized_message.message_type,
            "from_me": normalized_message.from_me,
            "is_group": normalized_message.is_group,
            "processable": normalized_message.processable,
            "ignore_reason": normalized_message.ignore_reason,
            "duplicate": duplicate,
            "accepted_for_processing": accepted_for_processing,
        },
    }
