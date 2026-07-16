from pydantic import BaseModel, ConfigDict


class CustomerResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    instance: str
    phone: str
    name: str | None
