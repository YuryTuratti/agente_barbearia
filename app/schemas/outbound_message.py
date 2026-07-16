from dataclasses import dataclass


@dataclass(frozen=True)
class OutboundMessageRegistrationResult:
    created: bool
    duplicate: bool
    record_id: str | None


@dataclass(frozen=True)
class EvolutionSendResult:
    success: bool
    external_message_id: str | None
    status_code: int
