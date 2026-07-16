from pydantic import BaseModel, ConfigDict


class OpenAITextResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    response_id: str | None = None
    model: str | None = None


class OpenAIToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str
    name: str
    arguments: str


class OpenAIResponseTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    output_text: str | None
    tool_calls: list[OpenAIToolCall]
    response_output_items: list[object]
