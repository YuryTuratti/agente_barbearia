from typing import Literal

from pydantic import BaseModel, ConfigDict

ImagePurpose = Literal["haircut_reference", "payment_receipt", "other", "unclear"]
AnalysisConfidence = Literal["low", "medium", "high"]
FadeLevel = Literal["none", "low", "mid", "high", "unclear"]
TopLength = Literal["very_short", "short", "medium", "long", "unclear"]


class HaircutReferenceAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    visible: bool
    probable_style_name: str | None
    features: list[str]
    fade_level: FadeLevel
    top_length: TopLength
    texture_description: str | None
    beard_visible: bool
    notes: str | None


class ImageAnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    purpose: ImagePurpose
    confidence: AnalysisConfidence
    safe_summary: str
    haircut: HaircutReferenceAnalysis | None
