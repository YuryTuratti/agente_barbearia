from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class AvailabilityDecision:
    can_check: bool
    reason: str | None = None
    safe_reply: str | None = None


MISSING_REPLIES = {
    "missing_service": "Qual serviço você quer fazer?",
    "missing_professional": "Com qual barbeiro você prefere marcar: Lucas ou Daniel?",
    "missing_date": "Para qual dia você quer marcar?",
    "missing_period": "Você prefere de manhã ou à tarde?",
}
PAST_DATE_REPLY = "Essa data já passou. Para qual dia você quer marcar?"
TOO_FAR_REPLY = (
    "Consigo verificar horários para os próximos 90 dias. Para qual dia você quer marcar?"
)
INVALID_DATE_REPLY = "Não consegui entender a data. Para qual dia você quer marcar?"
AVAILABILITY_FAILURE_REPLY = (
    "Não consegui verificar os horários agora. Pode tentar me falar outro horário "
    "ou chamar a barbearia diretamente."
)


def validate_availability_request(
    state: dict,
    *,
    today: date,
    max_days_ahead: int = 90,
) -> AvailabilityDecision:
    for field, reason in (
        ("requested_service", "missing_service"),
        ("requested_professional", "missing_professional"),
        ("requested_date", "missing_date"),
    ):
        if not state.get(field):
            return AvailabilityDecision(False, reason, MISSING_REPLIES[reason])
    if not state.get("requested_period") and not state.get("requested_time"):
        return AvailabilityDecision(False, "missing_period", MISSING_REPLIES["missing_period"])
    try:
        requested_date = date.fromisoformat(str(state["requested_date"]))
    except (TypeError, ValueError):
        return AvailabilityDecision(False, "invalid_date", INVALID_DATE_REPLY)
    if requested_date < today:
        return AvailabilityDecision(False, "date_in_past", PAST_DATE_REPLY)
    if requested_date > today + timedelta(days=max_days_ahead):
        return AvailabilityDecision(False, "date_too_far", TOO_FAR_REPLY)
    return AvailabilityDecision(True)


def no_slots_reply(state: dict) -> str:
    professional = state.get("requested_professional")
    if professional == "Lucas":
        return (
            "Não encontrei horário com Lucas nesse período. Quer tentar outro "
            "horário ou posso verificar com Daniel?"
        )
    if professional == "Daniel":
        return (
            "Não encontrei horário com Daniel nesse período. Quer tentar outro "
            "horário ou posso verificar com Lucas?"
        )
    return "Não encontrei horário nesse período. Quer tentar outro horário?"


def format_available_slots(state: dict, slots: list[dict]) -> str:
    period = state.get("requested_period")
    requested_time = state.get("requested_time")
    filtered = []
    for slot in slots:
        start = str(slot.get("start_time", ""))
        if requested_time and start != requested_time:
            continue
        hour = int(start[:2]) if len(start) >= 2 and start[:2].isdigit() else -1
        if period == "morning" and not 0 <= hour < 12:
            continue
        if period == "afternoon" and not 12 <= hour < 18:
            continue
        if period == "evening" and not 18 <= hour <= 23:
            continue
        filtered.append(slot)
    if not filtered:
        return no_slots_reply(state)
    times = [str(slot["start_time"]) for slot in filtered[:6]]
    if len(times) == 1:
        display = times[0]
    else:
        display = ", ".join(times[:-1]) + f" e {times[-1]}"
    barber = state.get("requested_professional")
    date_text = state.get("requested_date")
    barber_text = f" com {barber}" if barber and barber != "Tanto faz" else ""
    return f"Tenho {display}{barber_text} em {date_text}. Qual horário você prefere?"


def is_informational_request(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in (
        "quanto", "preço", "preco", "valor", "onde fica", "endereço", "endereco",
        "pagamento", "cartão", "cartao", "pix", "abre", "funciona", "horário de funcionamento",
    ))
