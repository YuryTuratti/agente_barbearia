import re

from app.exceptions.gemini import GeminiInvalidResponseError
from app.schemas.image_analysis import HaircutReferenceAnalysis, ImageAnalysisResult

MAX_FEATURE_LENGTH = 80


def sanitize_image_analysis(
    analysis: ImageAnalysisResult,
    *,
    max_features: int,
    max_summary_characters: int,
) -> ImageAnalysisResult:
    safe_summary = _clean_text(analysis.safe_summary)
    if not safe_summary:
        raise GeminiInvalidResponseError("Image analysis summary is empty.")
    safe_summary = safe_summary[:max_summary_characters].strip()

    haircut = analysis.haircut
    if analysis.purpose == "haircut_reference":
        if haircut is None:
            raise GeminiInvalidResponseError("Haircut reference analysis is missing.")
        haircut = _sanitize_haircut(haircut, max_features=max_features)
    elif haircut is not None:
        haircut = None

    if analysis.purpose == "payment_receipt":
        safe_summary = "Imagem possivelmente relacionada a comprovante de pagamento."
    elif analysis.purpose == "other":
        safe_summary = "Imagem nao parece ser uma referencia clara de corte de cabelo."
    elif analysis.purpose == "unclear":
        safe_summary = "Imagem sem clareza suficiente para identificar a referencia."

    return ImageAnalysisResult(
        purpose=analysis.purpose,
        confidence=analysis.confidence,
        safe_summary=safe_summary,
        haircut=haircut,
    )


def build_image_context(
    analysis: ImageAnalysisResult,
    *,
    caption: str | None,
    max_characters: int,
) -> str:
    caption_text = _clean_text(caption)
    parts: list[str] = []
    if caption_text:
        parts.append(f"Mensagem escrita pelo cliente: {caption_text}")

    if analysis.purpose == "haircut_reference":
        if analysis.haircut is None:
            raise GeminiInvalidResponseError("Haircut reference context is missing.")
        context_lines = [
            "O cliente enviou uma imagem de referencia de corte.",
            f"Descricao visual: {analysis.safe_summary}",
        ]
        if analysis.haircut.features:
            context_lines.append(
                "Caracteristicas observadas: "
                + "; ".join(analysis.haircut.features)
                + "."
            )
        if analysis.haircut.probable_style_name:
            context_lines.append(
                f"Nome aproximado do estilo: {analysis.haircut.probable_style_name}."
            )
        context_lines.append(
            "Esta analise e apenas uma referencia visual e nao corresponde "
            "automaticamente a um servico cadastrado."
        )
        parts.append("Contexto visual controlado: " + "\n".join(context_lines))
    elif analysis.purpose == "payment_receipt":
        parts.append(
            "O cliente enviou uma imagem que parece ser um comprovante de pagamento.\n"
            "A verificacao de pagamentos ainda nao esta disponivel.\n"
            "Nao afirme que o pagamento foi confirmado."
        )
    elif analysis.purpose == "other":
        parts.append(
            "O cliente enviou uma imagem que nao parece ser uma referencia clara "
            "de corte de cabelo."
        )
    else:
        parts.append(
            "O cliente enviou uma imagem, mas ela nao esta clara o suficiente "
            "para identificar a referencia."
        )

    return "\n\n".join(parts).strip()[:max_characters].strip()


def _sanitize_haircut(
    haircut: HaircutReferenceAnalysis,
    *,
    max_features: int,
) -> HaircutReferenceAnalysis:
    features: list[str] = []
    seen: set[str] = set()
    for feature in haircut.features:
        clean = _clean_text(feature)[:MAX_FEATURE_LENGTH].strip()
        key = clean.lower()
        if clean and key not in seen:
            features.append(clean)
            seen.add(key)
        if len(features) >= max_features:
            break

    return HaircutReferenceAnalysis(
        visible=haircut.visible,
        probable_style_name=_clean_optional(haircut.probable_style_name),
        features=features,
        fade_level=haircut.fade_level,
        top_length=haircut.top_length,
        texture_description=_clean_optional(haircut.texture_description),
        beard_visible=haircut.beard_visible,
        notes=_clean_optional(haircut.notes),
    )


def _clean_optional(value: str | None) -> str | None:
    clean = _clean_text(value)
    return clean or None


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.replace("\x00", "")).strip()
