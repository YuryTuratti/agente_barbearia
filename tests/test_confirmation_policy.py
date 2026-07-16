import pytest

from app.domain.confirmation import is_explicit_confirmation, is_explicit_rejection


@pytest.mark.parametrize(
    "text",
    [
        "sim",
        "confirmo",
        "pode confirmar",
        "pode marcar",
        "pode cancelar",
        "pode reagendar",
        "CONFIRMO!",
        "Está confirmado.",
    ],
)
def test_explicit_confirmations(text: str) -> None:
    assert is_explicit_confirmation(text) is True


@pytest.mark.parametrize(
    "text",
    ["talvez", "acho que sim", "depois", "qual seria o valor?", "não", "não confirma", ""],
)
def test_ambiguous_or_negative_messages_are_not_confirmation(text: str) -> None:
    assert is_explicit_confirmation(text) is False


@pytest.mark.parametrize("text", ["não", "não quero", "deixa para lá", "pode descartar", "não confirma"])
def test_explicit_rejections(text: str) -> None:
    assert is_explicit_rejection(text) is True


@pytest.mark.parametrize("text", ["", "cancelar meu agendamento", "talvez"])
def test_non_rejections(text: str) -> None:
    assert is_explicit_rejection(text) is False
