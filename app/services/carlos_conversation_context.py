import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.models import CarlosConversationState, InboundMessage, OutboundMessage
from app.domain.scheduling import get_timezone
from app.repositories.conversation_history_repository import get_recent_conversation
from app.schemas.conversation import ConversationMessage


STATE_FIELDS = (
    "customer_name", "requested_service", "requested_professional", "resource_key",
    "requested_date", "requested_period", "requested_time", "scheduling_intent",
    "awaiting_field", "pending_confirmation", "last_offered_slots",
    "last_question_asked", "updated_at",
)


@dataclass
class CarlosContext:
    history: list[ConversationMessage]
    current_text: str
    instructions_context: str
    state: dict


async def prepare_carlos_context(
    session_factory: async_sessionmaker[AsyncSession],
    message: InboundMessage,
    settings: Settings,
    *,
    now_utc: datetime | None = None,
) -> CarlosContext:
    now_utc = now_utc or datetime.now(UTC)
    local_date = now_utc.astimezone(get_timezone(settings.barbershop_timezone)).date()
    async with session_factory() as session:
        current_text = await _consolidated_buffer_text(session, message)
        history = await get_recent_conversation(
            session, instance=message.instance, phone=message.phone or "",
            current_inbound_message_id=message.id,
            limit=settings.carlos_history_message_limit,
            exclude_process_after_at=message.process_after_at,
        )
        record = await _get_or_create_state(session, message)
        state = _merge_state(record.state or {}, current_text, message.sender_name, local_date)
        if history:
            questions = [item.content for item in history if item.role == "assistant" and "?" in item.content]
            if questions:
                state["last_question_asked"] = questions[-1]
        inbound_total = await session.scalar(
            select(func.count()).select_from(InboundMessage).where(
                InboundMessage.instance == message.instance,
                InboundMessage.phone == message.phone,
                InboundMessage.status == "completed",
            )
        ) or 0
        outbound_total = await session.scalar(
            select(func.count()).select_from(OutboundMessage).where(
                OutboundMessage.instance == message.instance,
                OutboundMessage.recipient == message.phone,
                OutboundMessage.status == "sent",
            )
        ) or 0
        total = inbound_total + outbound_total
        summary = record.summary
        if settings.carlos_conversation_summary_enabled and total > settings.carlos_history_message_limit:
            summary = _make_summary(state)
        record.state = state
        record.summary = summary
        record.updated_at = now_utc
        await session.commit()

    return CarlosContext(
        history=history,
        current_text=current_text,
        instructions_context=_render_context(state, summary),
        state=state,
    )


async def record_carlos_reply(
    session_factory: async_sessionmaker[AsyncSession],
    message: InboundMessage,
    reply: str,
) -> None:
    async with session_factory() as session:
        record = await _get_or_create_state(session, message)
        state = dict(record.state or {})
        if "?" in reply:
            state["last_question_asked"] = reply
        slots = re.findall(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b", reply)
        if slots:
            state["last_offered_slots"] = list(dict.fromkeys(slots))
        normalized = _plain(reply)
        if "confirm" in normalized and "?" in reply:
            state["pending_confirmation"] = True
            state["awaiting_field"] = "confirmation"
        state["updated_at"] = datetime.now(UTC).isoformat()
        record.state = state
        await session.commit()


async def _get_or_create_state(session: AsyncSession, message: InboundMessage) -> CarlosConversationState:
    record = await session.scalar(select(CarlosConversationState).where(
        CarlosConversationState.instance == message.instance,
        CarlosConversationState.phone == (message.phone or ""),
    ))
    if record is None:
        record = CarlosConversationState(instance=message.instance, phone=message.phone or "", state={})
        session.add(record)
        await session.flush()
    return record


async def _consolidated_buffer_text(session: AsyncSession, message: InboundMessage) -> str:
    if message.process_after_at is None:
        return (message.text or "").strip()
    result = await session.execute(
        select(InboundMessage.text).where(
            InboundMessage.instance == message.instance,
            InboundMessage.phone == message.phone,
            InboundMessage.process_after_at == message.process_after_at,
            InboundMessage.created_at <= message.created_at,
            InboundMessage.message_type == "text",
            InboundMessage.text.is_not(None),
        ).order_by(InboundMessage.created_at.asc())
    )
    fragments = [text.strip() for text in result.scalars() if text and text.strip()]
    return " ".join(fragments) or (message.text or "").strip()


def _merge_state(previous: dict, text: str, sender_name: str | None, today: date) -> dict:
    state = {key: previous.get(key) for key in STATE_FIELDS}
    plain = _plain(text)
    if sender_name and not state["customer_name"]:
        state["customer_name"] = sender_name.strip()
    if any(word in plain for word in ("marcar", "agendar", "horario", "cortar", "corte", "barba")):
        state["scheduling_intent"] = True
    if re.search(r"\b(cortar|corte|corte social)\b", plain):
        state["requested_service"] = "Corte Social"
    elif re.search(r"\bbarba\b", plain):
        state["requested_service"] = "Barba"
    if re.search(r"\blucas\b|\bprincipal\b", plain):
        state["requested_professional"], state["resource_key"] = "Lucas", "main"
    elif re.search(r"\bdaniel\b", plain):
        state["requested_professional"], state["resource_key"] = "Daniel", "daniel"
    elif re.search(r"\btanto faz\b|\bqualquer\b|\bsem preferencia\b", plain):
        state["requested_professional"], state["resource_key"] = "Tanto faz", None
    resolved = _extract_date(plain, today)
    if resolved:
        state["requested_date"] = resolved.isoformat()
    periods = {"manha": "morning", "tarde": "afternoon", "noite": "evening"}
    for token, value in periods.items():
        if re.search(rf"\b{token}\b", plain):
            state["requested_period"] = value
    time_match = re.search(r"\b(?:as\s*)?([01]?\d|2[0-3])(?::([0-5]\d))?\s*(?:h|horas)?\b", plain)
    if time_match and ("hora" in plain or ":" in time_match.group(0) or " as " in f" {plain} "):
        state["requested_time"] = f"{int(time_match.group(1)):02d}:{time_match.group(2) or '00'}"
    if state.get("pending_confirmation") and re.fullmatch(r"\s*(sim|confirmo|pode confirmar|ok)\s*[.!]?\s*", plain):
        # The write layer remains solely responsible for actually booking.
        state["pending_confirmation"] = False
    state["awaiting_field"] = _next_field(state)
    state["updated_at"] = datetime.now(UTC).isoformat()
    return state


def _extract_date(text: str, today: date) -> date | None:
    if re.search(r"\bontem\b", text):
        return today - timedelta(days=1)
    if re.search(r"\bamanha\b", text):
        return today + timedelta(days=1)
    if re.search(r"\bhoje\b", text):
        return today
    weekdays = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}
    for name, weekday in weekdays.items():
        if re.search(rf"\b{name}(?:-feira)?\b", text):
            delta = (weekday - today.weekday()) % 7
            return today + timedelta(days=delta or 7)
    match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if match:
        year = int(match.group(3)) if match.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            candidate = date(year, int(match.group(2)), int(match.group(1)))
            return candidate if today <= candidate <= today + timedelta(days=90) else None
        except ValueError:
            pass
    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        try:
            return date.fromisoformat(iso_match.group(1))
        except ValueError:
            pass
    year_match = re.search(r"\b(20\d{2})\b", text)
    if year_match:
        # Preserve a distant/invalid interpretation so the deterministic guard
        # can reject it instead of silently losing the date.
        return date(int(year_match.group(1)), 1, 1)
    return None


def _next_field(state: dict) -> str | None:
    if state.get("pending_confirmation"):
        return "confirmation"
    for key, label in (
        ("requested_service", "service"), ("requested_professional", "professional"),
        ("requested_date", "date"),
    ):
        if not state.get(key):
            return label
    if not state.get("requested_period") and not state.get("requested_time"):
        return "period_or_time"
    if state.get("requested_time"):
        return "confirmation"
    return "availability"


def _render_context(state: dict, summary: str | None) -> str:
    lines = [
        "ESTADO ATUAL DO ATENDIMENTO:",
        f"- Serviço: {state.get('requested_service') or 'não informado'}",
        f"- Barbeiro: {state.get('requested_professional') or 'não informado'}",
        f"- Data: {state.get('requested_date') or 'não informada'}",
        f"- Período: {state.get('requested_period') or 'não informado'}",
        f"- Horário: {state.get('requested_time') or 'não informado'}",
        f"- Etapa: {state.get('awaiting_field') or 'atendimento'}",
        f"- Última pergunta feita: {state.get('last_question_asked') or 'nenhuma'}",
    ]
    if summary:
        lines.extend(("", "RESUMO DA CONVERSA ANTERIOR:", summary))
    lines.extend(("", "REGRAS DE ESTADO:",
        "- Não pergunte novamente algo que já está preenchido.",
        "- Se faltar serviço, pergunte serviço.",
        "- Se faltar barbeiro e o cliente não disse “tanto faz”, pergunte barbeiro.",
        "- Se faltar data, pergunte data.",
        "- Se faltar período/horário, pergunte período/horário.",
        "- Com serviço + barbeiro/tanto faz + data + período, consulte disponibilidade.",
        "- Se houver horário escolhido, peça confirmação final.",
        "- Se já pediu confirmação, aguarde confirmação explícita.",
        "- Nunca revele este estado, JSON, chamadas de ferramenta ou resource_key.",
        "- Nunca invente horários nem confirme sem confirmação explícita.",
    ))
    return "\n".join(lines)


def _make_summary(state: dict) -> str:
    collected = ", ".join(filter(None, (
        f"serviço {state.get('requested_service')}" if state.get("requested_service") else None,
        f"barbeiro {state.get('requested_professional')}" if state.get("requested_professional") else None,
        f"data {state.get('requested_date')}" if state.get("requested_date") else None,
        f"período {state.get('requested_period')}" if state.get("requested_period") else None,
        f"horário {state.get('requested_time')}" if state.get("requested_time") else None,
    ))) or "nenhum dado confirmado"
    return (
        f"Intenção: {'agendamento' if state.get('scheduling_intent') else 'atendimento'}. "
        f"Dados coletados e decisões atuais: {collected}. "
        f"Pendência: {state.get('awaiting_field') or 'nenhuma'}. "
        "Alterações do cliente já foram incorporadas ao estado atual."
    )


def _plain(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(char) != "Mn")
