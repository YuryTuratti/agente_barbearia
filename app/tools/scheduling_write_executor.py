import json
from datetime import time

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.database.models import InboundMessage
from app.exceptions.scheduling import (
    AppointmentNotFoundError,
    AppointmentNotScheduledError,
    AppointmentOwnershipError,
    BookingNoticeError,
    BookingTooFarAheadError,
    BusinessClosedError,
    InactiveServiceError,
    ServiceNotFoundError,
    SlotUnavailableError,
)
from app.exceptions.scheduling_actions import (
    ActionNotConfirmableError,
    ConfirmationDataChangedError,
    ConfirmationNotExplicitError,
    ConfirmationRequiresNewMessageError,
    NoPendingActionError,
    PendingActionExpiredError,
    RejectionNotExplicitError,
)
from app.schemas.scheduling_action import (
    CancelAppointmentActionPayload,
    CreateAppointmentActionPayload,
    RescheduleAppointmentActionPayload,
)
from app.schemas.tooling import (
    ConfirmPendingActionArguments,
    DiscardPendingActionArguments,
    PrepareCancelAppointmentArguments,
    PrepareCreateAppointmentArguments,
    PrepareRescheduleAppointmentArguments,
    ToolErrorResult,
    ToolExecutionResult,
)
from app.services.scheduling_action_service import SchedulingActionService
from app.repositories.barbershop_resource_repository import normalize_barber
from app.tools.scheduling_definitions import (
    LIST_AVAILABLE_SLOTS_TOOL_NAME,
    LIST_MY_APPOINTMENTS_TOOL_NAME,
    LIST_SERVICES_TOOL_NAME,
)
from app.tools.scheduling_executor import SchedulingToolExecutor
from app.tools.scheduling_write_definitions import (
    CONFIRM_PENDING_ACTION_TOOL_NAME,
    DISCARD_PENDING_ACTION_TOOL_NAME,
    PREPARE_CANCEL_APPOINTMENT_TOOL_NAME,
    PREPARE_CREATE_APPOINTMENT_TOOL_NAME,
    PREPARE_RESCHEDULE_APPOINTMENT_TOOL_NAME,
)


class SchedulingWriteToolExecutor:
    def __init__(
        self,
        *,
        read_executor: SchedulingToolExecutor,
        action_service: SchedulingActionService,
    ) -> None:
        self._read_executor = read_executor
        self._action_service = action_service

    async def execute(
        self,
        *,
        tool_name: str,
        arguments_json: str,
        message: InboundMessage,
    ) -> ToolExecutionResult:
        if tool_name in {
            LIST_SERVICES_TOOL_NAME,
            LIST_AVAILABLE_SLOTS_TOOL_NAME,
            LIST_MY_APPOINTMENTS_TOOL_NAME,
        }:
            return await self._read_executor.execute(
                tool_name=tool_name,
                arguments_json=arguments_json,
                message=message,
            )

        try:
            if tool_name == PREPARE_CREATE_APPOINTMENT_TOOL_NAME:
                args = PrepareCreateAppointmentArguments.model_validate_json(arguments_json or "{}")
                result = await self._action_service.prepare_create(
                    message=message,
                    payload=CreateAppointmentActionPayload(
                        service_ids=args.service_ids,
                        local_date=args.local_date,
                        local_start_time=_parse_hhmm(args.local_start_time),
                        customer_name=args.customer_name,
                        resource_key=normalize_barber(args.barber) or "main",
                    ),
                )
                return _ok(tool_name, result.model_dump(mode="json"))
            if tool_name == PREPARE_CANCEL_APPOINTMENT_TOOL_NAME:
                args = PrepareCancelAppointmentArguments.model_validate_json(arguments_json or "{}")
                result = await self._action_service.prepare_cancel(
                    message=message,
                    payload=CancelAppointmentActionPayload(
                        appointment_id=args.appointment_id,
                        reason=args.reason,
                    ),
                )
                return _ok(tool_name, result.model_dump(mode="json"))
            if tool_name == PREPARE_RESCHEDULE_APPOINTMENT_TOOL_NAME:
                args = PrepareRescheduleAppointmentArguments.model_validate_json(arguments_json or "{}")
                result = await self._action_service.prepare_reschedule(
                    message=message,
                    payload=RescheduleAppointmentActionPayload(
                        appointment_id=args.appointment_id,
                        new_local_date=args.new_local_date,
                        new_local_start_time=_parse_hhmm(args.new_local_start_time),
                        resource_key=normalize_barber(args.barber),
                    ),
                )
                return _ok(tool_name, result.model_dump(mode="json"))
            if tool_name == CONFIRM_PENDING_ACTION_TOOL_NAME:
                ConfirmPendingActionArguments.model_validate_json(arguments_json or "{}")
                result = await self._action_service.confirm_pending_action(message=message)
                return _ok(tool_name, result.model_dump(mode="json"))
            if tool_name == DISCARD_PENDING_ACTION_TOOL_NAME:
                DiscardPendingActionArguments.model_validate_json(arguments_json or "{}")
                result = await self._action_service.discard_pending_action(message=message)
                return _ok(tool_name, result.model_dump(mode="json"))
            return _error(tool_name, "invalid_arguments", "Ferramenta desconhecida.")
        except (ValidationError, ValueError, json.JSONDecodeError):
            return _error(tool_name, "invalid_arguments", "Os argumentos da ferramenta são inválidos.")
        except NoPendingActionError:
            return _error(tool_name, "no_pending_action", "Não existe ação aguardando confirmação.")
        except PendingActionExpiredError:
            return _error(tool_name, "pending_action_expired", "A confirmação expirou.")
        except ConfirmationRequiresNewMessageError:
            return _error(tool_name, "confirmation_requires_new_message", "A confirmação precisa vir em uma nova mensagem.")
        except ConfirmationNotExplicitError:
            return _error(tool_name, "confirmation_not_explicit", "A confirmação não foi explícita.")
        except RejectionNotExplicitError:
            return _error(tool_name, "rejection_not_explicit", "A rejeição não foi explícita.")
        except ConfirmationDataChangedError:
            return _error(tool_name, "confirmation_data_changed", "Os dados mudaram e precisam ser revisados.")
        except ActionNotConfirmableError:
            return _error(tool_name, "action_not_confirmable", "A ação não pode ser confirmada.")
        except AppointmentNotFoundError:
            return _error(tool_name, "appointment_not_found", "Agendamento não encontrado.")
        except AppointmentOwnershipError:
            return _error(tool_name, "appointment_not_owned", "Agendamento não encontrado.")
        except AppointmentNotScheduledError:
            return _error(tool_name, "appointment_not_scheduled", "O agendamento não está ativo.")
        except ServiceNotFoundError:
            return _error(tool_name, "service_not_found", "Um dos serviços informados não está disponível.")
        except InactiveServiceError:
            return _error(tool_name, "inactive_service", "Um dos serviços informados não está ativo.")
        except BusinessClosedError:
            return _error(tool_name, "business_closed", "A agenda está fechada nessa data.")
        except (BookingNoticeError, BookingTooFarAheadError):
            return _error(tool_name, "outside_booking_window", "A data informada não está disponível.")
        except SlotUnavailableError:
            return _error(tool_name, "slot_unavailable", "Esse horário não está mais disponível.")
        except SQLAlchemyError:
            return _error(tool_name, "temporary_error", "Não foi possível concluir agora.", retryable=True)
        except Exception:
            return _error(tool_name, "internal_error", "Não foi possível concluir a operação.")


def _parse_hhmm(value: str) -> time:
    return time.fromisoformat(value)


def _ok(tool_name: str, data: dict[str, object]) -> ToolExecutionResult:
    return ToolExecutionResult(ok=True, tool_name=tool_name, data=data)


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
