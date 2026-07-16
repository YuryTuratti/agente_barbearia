from datetime import time

from pydantic import BaseModel, ConfigDict


class BusinessHoursInterval(BaseModel):
    model_config = ConfigDict(frozen=True)

    opens_at: time
    closes_at: time
