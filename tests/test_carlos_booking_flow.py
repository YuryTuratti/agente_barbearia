import pytest

from app.prompts.carlos import CARLOS_SYSTEM_PROMPT
from app.prompts.carlos_scheduling import CARLOS_SCHEDULING_SYSTEM_PROMPT
from app.prompts.carlos_scheduling_write import CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT
from app.repositories.barbershop_resource_repository import normalize_barber
from app.services.carlos_response_service import normalize_carlos_reply


PROMPTS = (
    CARLOS_SYSTEM_PROMPT,
    CARLOS_SCHEDULING_SYSTEM_PROMPT,
    CARLOS_SCHEDULING_WRITE_SYSTEM_PROMPT,
)


@pytest.mark.parametrize("prompt", PROMPTS)
def test_all_carlos_prompts_enforce_booking_collection_order(prompt):
    assert "servico; barbeiro; data; periodo ou horario; confirmacao final" in prompt
    assert "Com qual barbeiro você prefere marcar: Lucas ou Daniel?" in prompt
    assert "Para qual dia você quer marcar?" in prompt
    assert "Você prefere de manhã ou à tarde?" in prompt
    assert "somente uma pergunta por mensagem" in prompt
    assert "servico, barbeiro (ou \"tanto faz\"), data e periodo/horario" in prompt


@pytest.mark.parametrize("prompt", PROMPTS)
def test_all_carlos_prompts_define_safe_confirmation_and_real_availability(prompt):
    assert "Ofereca apenas horarios retornados pela ferramenta" in prompt
    assert "O resumo obrigatoriamente contem servico, barbeiro, data e horario" in prompt
    assert "So execute depois de uma nova mensagem com confirmacao explicita" in prompt
    assert "Lucas (resource_key main) e Daniel (resource_key daniel)" in prompt


@pytest.mark.parametrize(
    ("unsafe", "expected"),
    [
        ("Qual dia da manhã você pretende marcar?", "Beleza, de manhã. Para qual dia?"),
        ("Qual dia da tarde vc pretende marcar?", "Beleza, à tarde. Para qual dia?"),
        ("Qual dia da noite você pretende marcar?", "Beleza, à noite. Para qual dia?"),
        ("Que dia você pretende marcar?", "Para qual dia você quer marcar?"),
        ("Qual dia vc pretende marcar?", "Para qual dia você quer marcar?"),
        ("Onde pretende se encontrar?", "O atendimento é na O Original Barbershop."),
        ("Você pretende marcar amanhã?", "Você quer marcar amanhã?"),
    ],
)
def test_reply_sanitizer_rewrites_forbidden_phrases(unsafe, expected):
    result = normalize_carlos_reply(unsafe, max_characters=500)
    assert result == expected
    lowered = result.casefold()
    for forbidden in (
        "qual dia da manhã", "qual dia da tarde", "qual dia da noite",
        "pretende marcar", "onde pretende se encontrar", "qual dia você pretende",
        "qual dia vc pretende",
    ):
        assert forbidden not in lowered


@pytest.mark.parametrize(
    "phrase",
    ["tanto faz", "qualquer um", "o primeiro disponível", "quem tiver horário", "sem preferência"],
)
def test_no_barber_preference_aliases_search_all_resources(phrase):
    assert normalize_barber(phrase) is None


def test_named_barbers_map_to_expected_resources():
    assert normalize_barber("Lucas") == "main"
    assert normalize_barber("Daniel") == "daniel"
