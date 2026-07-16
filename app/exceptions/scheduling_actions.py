class SchedulingActionError(Exception):
    pass


class NoPendingActionError(SchedulingActionError):
    pass


class PendingActionExpiredError(SchedulingActionError):
    pass


class ConfirmationRequiresNewMessageError(SchedulingActionError):
    pass


class ConfirmationNotExplicitError(SchedulingActionError):
    pass


class RejectionNotExplicitError(SchedulingActionError):
    pass


class ConfirmationDataChangedError(SchedulingActionError):
    pass


class ActionNotConfirmableError(SchedulingActionError):
    pass
