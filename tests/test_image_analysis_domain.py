import pytest

from app.domain.image_analysis import build_image_context, sanitize_image_analysis
from app.exceptions.gemini import GeminiInvalidResponseError
from app.schemas.image_analysis import HaircutReferenceAnalysis, ImageAnalysisResult


def test_sanitize_image_analysis_limits_and_deduplicates_features() -> None:
    analysis = _analysis(
        features=["laterais curtas", "", "laterais curtas", "degrade baixo", "volume no topo"],
        safe_summary="Resumo \x00 com acento",
    )

    sanitized = sanitize_image_analysis(
        analysis,
        max_features=2,
        max_summary_characters=20,
    )

    assert sanitized.safe_summary == "Resumo com acento"
    assert sanitized.haircut is not None
    assert sanitized.haircut.features == ["laterais curtas", "degrade baixo"]


def test_sanitize_image_analysis_rejects_haircut_reference_without_haircut() -> None:
    with pytest.raises(GeminiInvalidResponseError):
        sanitize_image_analysis(
            ImageAnalysisResult(
                purpose="haircut_reference",
                confidence="low",
                safe_summary="Referencia de corte.",
                haircut=None,
            ),
            max_features=8,
            max_summary_characters=1000,
        )


def test_sanitize_image_analysis_removes_haircut_from_non_haircut_purposes() -> None:
    receipt = sanitize_image_analysis(
        _analysis(purpose="payment_receipt"),
        max_features=8,
        max_summary_characters=1000,
    )
    other = sanitize_image_analysis(
        _analysis(purpose="other"),
        max_features=8,
        max_summary_characters=1000,
    )
    unclear = sanitize_image_analysis(
        _analysis(purpose="unclear"),
        max_features=8,
        max_summary_characters=1000,
    )

    assert receipt.haircut is None
    assert "pagamento" in receipt.safe_summary
    assert other.haircut is None
    assert unclear.haircut is None


def test_build_image_context_uses_controlled_templates_and_caption() -> None:
    context = build_image_context(
        _analysis(),
        caption="Quero algo parecido",
        max_characters=1000,
    )

    assert "Mensagem escrita pelo cliente: Quero algo parecido" in context
    assert "Contexto visual controlado" in context
    assert "laterais curtas" in context
    assert "servico cadastrado" in context
    assert "confidence" not in context
    assert "JSON" not in context


def test_build_image_context_for_receipt_does_not_confirm_payment() -> None:
    context = build_image_context(
        ImageAnalysisResult(
            purpose="payment_receipt",
            confidence="medium",
            safe_summary="Imagem possivelmente relacionada a comprovante.",
            haircut=None,
        ),
        caption=None,
        max_characters=1000,
    )

    assert "comprovante" in context
    assert "Nao afirme que o pagamento foi confirmado" in context
    assert "aprovado" not in context


def _analysis(
    *,
    purpose="haircut_reference",
    features: list[str] | None = None,
    safe_summary: str = "Corte com laterais curtas e volume no topo.",
) -> ImageAnalysisResult:
    return ImageAnalysisResult(
        purpose=purpose,
        confidence="medium",
        safe_summary=safe_summary,
        haircut=HaircutReferenceAnalysis(
            visible=True,
            probable_style_name="degrade baixo",
            features=features or ["laterais curtas", "volume no topo"],
            fade_level="low",
            top_length="medium",
            texture_description=None,
            beard_visible=False,
            notes=None,
        ),
    )
