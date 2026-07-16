import json
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import InboundMessage
from app.domain.barbershop_catalog import format_price_display, get_barbershop_info
from app.domain.clock import Clock, SystemClock
from app.domain.scheduling import validate_instance, validate_phone, validate_resource_key
from app.exceptions.scheduling import (
    BookingNoticeError,
    BookingTooFarAheadError,
    BusinessClosedError,
    InactiveServiceError,
    InvalidAppointmentTimeError,
    InvalidPhoneError,
    ServiceNotFoundError,
    SlotUnavailableError,
)
from app.repositories.service_repository import list_active_services
from app.repositories.barbershop_resource_repository import get_booking_resource, normalize_barber
from app.schemas.tooling import (
    ListAvailableSlotsArguments,
    GetBarbershopInfoArguments,
    ListMyAppointmentsArguments,
    ListServicesArguments,
    ToolErrorResult,
    ToolExecutionResult,
)
from app.services.availability_service import AvailabilityService
from app.services.scheduling_service import SchedulingService
from app.tools.scheduling_definitions import (
    GET_BARBERSHOP_INFO_TOOL_NAME,
    LIST_AVAILABLE_SLOTS_TOOL_NAME,
    LIST_MY_APPOINTMENTS_TOOL_NAME,
    LIST_SERVICES_TOOL_NAME,
)

logger = logging.getLogger(__name__)

ArgumentsT = TypeVar("ArgumentsT", bound=BaseModel)


class SchedulingToolExecutor:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock or SystemClock()

    async def execute(
        self,
        *,
        tool_name: str,
        arguments_json: str,
        message: InboundMessage,
    ) -> ToolExecutionResult:
        try:
            instance = validate_instance(message.instance)
            resource_key = validate_resource_key(self._settings.default_resource_key)
            if tool_name == LIST_MY_APPOINTMENTS_TOOL_NAME:
                validate_phone(message.phone or "")
        except InvalidPhoneError:
            return _error(tool_name, "customer_not_found", "Não consegui identificar o cliente atual.")
        except Exception:
            return _error(tool_name, "invalid_arguments", "Não consegui validar o contexto da consulta.")

        try:
            if tool_name == LIST_SERVICES_TOOL_NAME:
                _parse_arguments(ListServicesArguments, arguments_json)
                return await self._list_services(tool_name=tool_name)
            if tool_name == GET_BARBERSHOP_INFO_TOOL_NAME:
                _parse_arguments(GetBarbershopInfoArguments, arguments_json)
                return ToolExecutionResult(
                    ok=True,
                    tool_name=tool_name,
                    data=get_barbershop_info(),
                )
            if tool_name == LIST_AVAILABLE_SLOTS_TOOL_NAME:
                arguments = _parse_arguments(ListAvailableSlotsArguments, arguments_json)
                if len(arguments.service_ids) > self._settings.scheduling_max_services_per_appointment:
                    raise ValueError("Too many services.")
                return await self._list_available_slots(
                    tool_name=tool_name,
                    instance=instance,
                    resource_key=normalize_barber(arguments.barber),
                    arguments=arguments,
                )
            if tool_name == LIST_MY_APPOINTMENTS_TOOL_NAME:
                _parse_arguments(ListMyAppointmentsArguments, arguments_json)
                return await self._list_my_appointments(
                    tool_name=tool_name,
                    instance=instance,
                    phone=message.phone or "",
                )
            return _error(tool_name, "invalid_arguments", "Ferramenta desconhecida.")
        except ValidationError as error:
            if _is_local_date_validation_error(error):
                return _error(tool_name, "invalid_date", "A data deve estar no formato YYYY-MM-DD.")
            return _error(tool_name, "invalid_arguments", "Os argumentos da ferramenta são inválidos.")
        except (ValueError, json.JSONDecodeError):
            return _error(tool_name, "invalid_arguments", "Os argumentos da ferramenta são inválidos.")
        except ServiceNotFoundError:
            return _error(tool_name, "service_not_found", "Um dos serviços informados não está disponível.")
        except InactiveServiceError:
            return _error(tool_name, "inactive_service", "Um dos serviços informados não está ativo.")
        except BusinessClosedError:
            return _error(tool_name, "business_closed", "A agenda está fechada nessa data.")
        except (BookingNoticeError, BookingTooFarAheadError, InvalidAppointmentTimeError):
            return _error(tool_name, "outside_booking_window", "A data informada não está disponível para consulta.")
        except SlotUnavailableError:
            return _error(tool_name, "scheduling_unavailable", "Não foi possível consultar a agenda agora.")
        except SQLAlchemyError:
            logger.info("Scheduling tool database error: tool_name=%s", tool_name)
            return _error(
                tool_name,
                "temporary_error",
                "Não foi possível consultar a agenda agora.",
                retryable=True,
            )
        except Exception:
            logger.exception("Unexpected scheduling tool error: tool_name=%s", tool_name)
            return _error(tool_name, "internal_error", "Não foi possível concluir a consulta.")

    async def _list_services(self, *, tool_name: str) -> ToolExecutionResult:
        async with self._session_factory() as session:
            services = await list_active_services(session)
        return ToolExecutionResult(
            ok=True,
            tool_name=tool_name,
            data={
                "services": [
                    {
                        "id": service.id,
                        "slug": service.slug,
                        "name": service.name,
                        "description": service.description,
                        "duration_minutes": service.duration_minutes,
                        "duration_configured": service.duration_minutes > 0,
                        "booking_enabled": service.booking_enabled,
                        "price_type": service.price_type,
                        "price_cents": service.price_cents,
                        "price_display": format_price_display(
                            slug=service.slug,
                            price_cents=service.price_cents,
                        ),
                        "requires_quote": service.requires_quote,
                    }
                    for service in services
                ]
            },
        )

    async def _list_available_slots(
        self,
        *,
        tool_name: str,
        instance: str,
        resource_key: str | None,
        arguments: ListAvailableSlotsArguments,
    ) -> ToolExecutionResult:
        async with self._session_factory() as session:
            if resource_key == "__invalid__" or (resource_key and resource_key != self._settings.default_resource_key and await get_booking_resource(session, instance=instance, resource_key=resource_key) is None):
                return _error(tool_name, "barber_unavailable", "Esse profissional não está disponível para agendamentos.")
            service = AvailabilityService(
                session,
                settings=self._settings,
                clock=self._clock,
            )
            result = await service.list_available_slots(
                instance=instance,
                local_date=arguments.local_date,
                service_ids=arguments.service_ids,
                resource_key=resource_key,
            )
        return ToolExecutionResult(
            ok=True,
            tool_name=tool_name,
            data={
                "local_date": result.local_date.isoformat(),
                "timezone": result.timezone,
                "total_duration_minutes": result.total_duration_minutes,
                "slots": [
                    {
                        "start_time": slot.start_time.strftime("%H:%M"),
                        "end_time": slot.end_time.strftime("%H:%M"),
                        "resource_key": slot.resource_key,
                        "barber": slot.barber_name,
                    }
                    for slot in result.slots
                ],
            },
        )

    async def _list_my_appointments(
        self,
        *,
        tool_name: str,
        instance: str,
        phone: str,
    ) -> ToolExecutionResult:
        async with self._session_factory() as session:
            service = SchedulingService(
                session,
                settings=self._settings,
                clock=self._clock,
            )
            appointments = await service.list_future_appointments(
                instance=instance,
                phone=phone,
            )
        return ToolExecutionResult(
            ok=True,
            tool_name=tool_name,
            data={
                "appointments": [
                    {
                        "id": appointment.id,
                        "resource_key": appointment.resource_key,
                        "barber": appointment.barber_name,
                        "confirmation_code": appointment.confirmation_code,
                        "status": appointment.status,
                        "local_date": appointment.local_date.isoformat(),
                        "local_start_time": appointment.local_start_time.strftime("%H:%M"),
                        "local_end_time": appointment.local_end_time.strftime("%H:%M"),
                        "timezone": appointment.timezone,
                        "services": [
                            {
                                "service_id": snapshot.service_id,
                                "name": snapshot.name,
                                "duration_minutes": snapshot.duration_minutes,
                                "price_cents": snapshot.price_cents,
                            }
                            for snapshot in appointment.services
                        ],
                        "total_duration_minutes": appointment.total_duration_minutes,
                        "total_price_cents": appointment.total_price_cents,
                    }
                    for appointment in appointments
                ]
            },
        )


def _parse_arguments(model: type[ArgumentsT], arguments_json: str) -> ArgumentsT:
    return model.model_validate_json(arguments_json or "{}")


def _error(
    tool_name: str,
    code: str,
    message: str,
    *,
    retryable: bool = False,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        ok=False,
        tool_name=tool_name,
        error=ToolErrorResult(code=code, message=message, retryable=retryable),
    )


def _is_local_date_validation_error(error: ValidationError) -> bool:
    return any(tuple(item.get("loc", ())) == ("local_date",) for item in error.errors())
