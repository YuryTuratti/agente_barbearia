import re
import unicodedata

_CONFIRMATIONS = {
    "sim",
    "sim pode marcar",
    "confirmo",
    "pode confirmar",
    "pode marcar",
    "pode agendar",
    "pode cancelar",
    "pode reagendar",
    "esta confirmado",
    "confirmado",
    "pode fazer",
}

_REJECTIONS = {
    "nao",
    "nao quero",
    "deixa para la",
    "pode descartar",
    "cancela essa solicitacao",
    "nao confirma",
    "ainda nao",
}

_NEGATION_WORDS = {"nao", "nunca", "jamais"}


def is_explicit_confirmation(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized or "?" in text:
        return False
    if any(word in normalized.split() for word in _NEGATION_WORDS):
        return False
    if normalized in {"talvez", "acho que sim", "depois", "vou pensar", "nao sei", "pode ser"}:
        return False
    return normalized in _CONFIRMATIONS


def is_explicit_rejection(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False
    return normalized in _REJECTIONS


def _normalize(text: str) -> str:
    clean = unicodedata.normalize("NFD", text.strip().lower())
    clean = "".join(char for char in clean if unicodedata.category(char) != "Mn")
    clean = re.sub(r"[^\w\s]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean
