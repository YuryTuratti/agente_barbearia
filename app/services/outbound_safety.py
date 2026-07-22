import re
from datetime import date, timedelta

SAFE_FALLBACK_REPLY = "Desculpa, não consegui entender bem. Pode me dizer o que você precisa?"
TOOL_LEAK_FALLBACK_REPLY = "Qual serviço você quer agendar?"
OUTSIDE_WINDOW_REPLY = (
    "Consigo verificar horários para os próximos 90 dias. Para qual dia você quer marcar?"
)

_INTERNAL_MARKERS = (
    "tool",
    '"tool"',
    '"arguments"',
    "check_availability",
    "create_appointment",
    "resource_key",
    "```json",
)


def secure_outbound_text(
    text: str,
    *,
    local_today: date | None = None,
    max_days_ahead: int = 90,
) -> str:
    """Return only customer-safe prose; internal payloads never cross this boundary."""
    clean = (text or "").replace("\x00", "").strip()
    lowered = clean.lower()
    leaked = any(marker in lowered for marker in _INTERNAL_MARKERS) or _starts_with_json(clean)

    if leaked and local_today is not None:
        for raw_date in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", clean):
            try:
                requested = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if requested < local_today or requested > local_today + timedelta(days=max_days_ahead):
                return OUTSIDE_WINDOW_REPLY

    if leaked:
        # Textual tool output is untrusted: the prose appended after JSON may
        # claim availability without any successful internal execution.
        return TOOL_LEAK_FALLBACK_REPLY

    # A brace in a WhatsApp reply is never needed by Carlos and may be a partial
    # payload. Fail closed instead of trying to repair an unknown structure.
    lowered = clean.lower()
    if not clean or "{" in clean or any(marker in lowered for marker in _INTERNAL_MARKERS):
        return SAFE_FALLBACK_REPLY
    return clean.strip()


def _starts_with_json(text: str) -> bool:
    return text.lstrip().startswith("{")

