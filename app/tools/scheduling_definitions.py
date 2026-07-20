from typing import Any

LIST_SERVICES_TOOL_NAME = "list_services"
GET_BARBERSHOP_INFO_TOOL_NAME = "get_barbershop_info"
LIST_AVAILABLE_SLOTS_TOOL_NAME = "list_available_slots"
LIST_MY_APPOINTMENTS_TOOL_NAME = "list_my_appointments"


def get_scheduling_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": LIST_SERVICES_TOOL_NAME,
            "description": (
                "Lista os serviços ativos realmente cadastrados na Turatti Barbe, "
                "incluindo identificador, nome, descrição, duração e preço. Use "
                "esta ferramenta antes de informar serviços, preços ou durações."
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
            "name": GET_BARBERSHOP_INFO_TOOL_NAME,
            "description": (
                "Retorna informacoes confirmadas da barbearia, incluindo formas "
                "de pagamento estruturadas para resposta publica."
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
            "name": LIST_AVAILABLE_SLOTS_TOOL_NAME,
            "description": (
                "Consulta horários realmente disponíveis para uma data e uma lista "
                "de serviços cadastrados. Use somente IDs de serviços retornados "
                "por list_services."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "local_date": {
                        "type": "string",
                        "description": "Data local no formato YYYY-MM-DD.",
                    },
                    "service_ids": {
                        "type": "array",
                        "description": "IDs dos serviços cadastrados.",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "barber": {"type": ["string", "null"], "description": "Profissional: lucas, daniel, main, barbeiro principal, tanto faz, qualquer ou sem preferencia. Null busca todos os profissionais."},
                },
                "required": ["local_date", "service_ids", "barber"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": LIST_MY_APPOINTMENTS_TOOL_NAME,
            "description": (
                "Lista os próximos agendamentos ativos do cliente atual. A "
                "identidade do cliente é determinada pelo telefone do WhatsApp e "
                "não deve ser solicitada novamente."
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
