import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.clients.gemini_image_client import GeminiImageClient
from app.exceptions.gemini import GeminiInvalidResponseError, GeminiPermanentError, GeminiTemporaryError
from app.prompts.image_analysis import IMAGE_ANALYSIS_PROMPT
from app.schemas.image_analysis import HaircutReferenceAnalysis, ImageAnalysisResult
from app.schemas.media import DownloadedMedia


@pytest.mark.anyio
async def test_gemini_image_client_uses_async_model_and_parsed_response() -> None:
    parsed = _haircut_result()
    sdk = FakeGeminiSdk(response=SimpleNamespace(parsed=parsed))
    client = GeminiImageClient(
        api_key=SecretStr("gemini-key"),
        model="gemini-test",
        timeout_seconds=30,
        max_output_tokens=123,
        temperature=0.2,
        sdk_client=sdk,
    )

    result = await client.analyze(image=_image())

    assert result == parsed
    call = sdk.calls[0]
    assert call["model"] == "gemini-test"
    assert call["config"]["response_mime_type"] == "application/json"
    assert call["config"]["response_schema"] is ImageAnalysisResult
    assert call["config"]["max_output_tokens"] == 123
    assert call["config"]["temperature"] == 0.2
    assert call["contents"][0]["text"] == IMAGE_ANALYSIS_PROMPT
    assert call["contents"][1]["data"] == b"image-bytes"
    assert call["contents"][1]["mime_type"] == "image/jpeg"
    assert "phone" not in call
    assert "instance" not in call


@pytest.mark.anyio
async def test_gemini_image_client_validates_json_text_response() -> None:
    sdk = FakeGeminiSdk(response=SimpleNamespace(text=_haircut_result().model_dump_json()))
    client = GeminiImageClient(
        api_key=SecretStr("gemini-key"),
        model="gemini-test",
        timeout_seconds=30,
        max_output_tokens=123,
        temperature=0.2,
        sdk_client=sdk,
    )

    result = await client.analyze(image=_image())

    assert result.purpose == "haircut_reference"


@pytest.mark.anyio
async def test_gemini_image_client_maps_invalid_and_status_errors_safely() -> None:
    invalid_client = GeminiImageClient(
        api_key=SecretStr("gemini-key"),
        model="gemini-test",
        timeout_seconds=30,
        max_output_tokens=123,
        temperature=0.2,
        sdk_client=FakeGeminiSdk(response=SimpleNamespace(text=json.dumps({"extra": "field"}))),
    )
    temporary_client = GeminiImageClient(
        api_key=SecretStr("gemini-key"),
        model="gemini-test",
        timeout_seconds=30,
        max_output_tokens=123,
        temperature=0.2,
        sdk_client=FakeGeminiSdk(error=StatusError(500)),
    )
    permanent_client = GeminiImageClient(
        api_key=SecretStr("gemini-key"),
        model="gemini-test",
        timeout_seconds=30,
        max_output_tokens=123,
        temperature=0.2,
        sdk_client=FakeGeminiSdk(error=StatusError(401)),
    )

    with pytest.raises(GeminiInvalidResponseError):
        await invalid_client.analyze(image=_image())
    with pytest.raises(GeminiTemporaryError) as temporary:
        await temporary_client.analyze(image=_image())
    with pytest.raises(GeminiPermanentError) as permanent:
        await permanent_client.analyze(image=_image())

    assert "gemini-key" not in str(temporary.value)
    assert "gemini-key" not in str(permanent.value)


@pytest.mark.anyio
async def test_gemini_image_client_does_not_close_injected_client() -> None:
    sdk = FakeGeminiSdk(response=SimpleNamespace(parsed=_haircut_result()))
    client = GeminiImageClient(
        api_key=SecretStr("gemini-key"),
        model="gemini-test",
        timeout_seconds=30,
        max_output_tokens=123,
        temperature=0.2,
        sdk_client=sdk,
    )

    await client.close()

    assert sdk.closed is False


class FakeModels:
    def __init__(self, owner: "FakeGeminiSdk") -> None:
        self._owner = owner

    async def generate_content(self, **kwargs):
        self._owner.calls.append(kwargs)
        if self._owner.error is not None:
            raise self._owner.error
        return self._owner.response


class FakeAio:
    def __init__(self, owner: "FakeGeminiSdk") -> None:
        self._owner = owner
        self.models = FakeModels(owner)

    async def close(self) -> None:
        self._owner.closed = True


class FakeGeminiSdk:
    def __init__(self, *, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []
        self.closed = False
        self.aio = FakeAio(self)


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def _image() -> DownloadedMedia:
    return DownloadedMedia(
        content=b"image-bytes",
        mimetype="image/jpeg",
        file_name="reference.jpg",
        size_bytes=11,
        sha256="hash",
        source="inline_base64",
    )


def _haircut_result() -> ImageAnalysisResult:
    return ImageAnalysisResult(
        purpose="haircut_reference",
        confidence="medium",
        safe_summary="Corte com laterais curtas e volume no topo.",
        haircut=HaircutReferenceAnalysis(
            visible=True,
            probable_style_name="degrade baixo",
            features=["laterais curtas", "volume no topo"],
            fade_level="low",
            top_length="medium",
            texture_description=None,
            beard_visible=False,
            notes=None,
        ),
    )
