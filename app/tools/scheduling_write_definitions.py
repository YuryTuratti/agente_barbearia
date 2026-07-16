from typing import Any

from app.tools.scheduling_definitions import get_scheduling_tool_definitions

PREPARE_CREATE_APPOINTMENT_TOOL_NAME = "prepare_create_appointment"
PREPARE_CANCEL_APPOINTMENT_TOOL_NAME = "prepare_cancel_appointment"
PREPARE_RESCHEDULE_APPOINTMENT_TOOL_NAME = "prepare_reschedule_appointment"
CONFIRM_PENDING_ACTION_TOOL_NAME = "confirm_pending_action"
DISCARD_PENDING_ACTION_TOOL_NAME = "discard_pending_action"


def get_scheduling_write_tool_definitions() -> list[dict[str, Any]]:
    return [
        *get_scheduling_tool_definitions(),
        {
            "type": "function",
            "name": PREPARE_CREATE_APPOINTMENT_TOOL_NAME,
            "description": (
                "Valida e prepara um agendamento para confirmação. Esta ferramenta "
                "não cria o agendamento. Use somente depois de identificar os "
                "serviços, a data e o horário desejados e consultar a disponibilidade."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "service_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "local_date": {"type": "string", "description": "Data local no formato YYYY-MM-DD."},
                    "local_start_time": {"type": "string", "description": "Horário local no formato HH:MM."},
                    "customer_name": {"type": ["string", "null"], "description": "Nome informado pelo cliente ou null."},
                    "barber": {"type": ["string", "null"], "description": "Profissional escolhido ou null para sem preferencia."},
                },
                "required": ["service_ids", "local_date", "local_start_time", "customer_name", "barber"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": PREPARE_CANCEL_APPOINTMENT_TOOL_NAME,
            "description": (
                "Valida e prepara o cancelamento de um agendamento do cliente atual. "
                "Esta ferramenta não cancela o agendamento. Use o ID obtido por "
                "list_my_appointments e depois peça confirmação explícita."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "reason": {"type": ["string", "null"]},
                },
                "required": ["appointment_id", "reason"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": PREPARE_RESCHEDULE_APPOINTMENT_TOOL_NAME,
            "description": (
                "Valida e prepara o reagendamento de um agendamento existente. Esta "
                "ferramenta não altera o agendamento. Use o ID obtido por "
                "list_my_appointments e consulte a disponibilidade antes de preparar."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "new_local_date": {"type": "string", "description": "Nova data local no formato YYYY-MM-DD."},
                    "new_local_start_time": {"type": "string", "description": "Novo horário local no formato HH:MM."},
                    "barber": {"type": ["string", "null"], "description": "Novo profissional; null mantem o atual."},
                },
                "required": ["appointment_id", "new_local_date", "new_local_start_time", "barber"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": CONFIRM_PENDING_ACTION_TOOL_NAME,
            "description": (
                "Confirma e executa a ação de agenda que está aguardando confirmação "
                "para o cliente atual. Use somente quando a mensagem atual do cliente "
                "confirmar explicitamente a operação preparada em uma mensagem anterior."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": DISCARD_PENDING_ACTION_TOOL_NAME,
            "description": (
                "Descarta a ação de agenda que está aguardando confirmação para o "
                "cliente atual. Use somente quando a mensagem atual rejeitar claramente "
                "a operação preparada."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    ]
