class SchedulingError(Exception):
    pass


class InvalidPhoneError(SchedulingError):
    pass


class ServiceNotFoundError(SchedulingError):
    pass


class InactiveServiceError(SchedulingError):
    pass


class BusinessClosedError(SchedulingError):
    pass


class OutsideBusinessHoursError(SchedulingError):
    pass


class SlotUnavailableError(SchedulingError):
    pass


class AppointmentNotFoundError(SchedulingError):
    pass


class AppointmentOwnershipError(SchedulingError):
    pass


class AppointmentNotScheduledError(SchedulingError):
    pass


class InvalidAppointmentTimeError(SchedulingError):
    pass


class BookingNoticeError(SchedulingError):
    pass


class BookingTooFarAheadError(SchedulingError):
    pass


class IdempotencyConflictError(SchedulingError):
    pass
