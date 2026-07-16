class GeminiClientError(Exception):
    pass


class GeminiTemporaryError(GeminiClientError):
    pass


class GeminiPermanentError(GeminiClientError):
    pass


class GeminiInvalidResponseError(GeminiTemporaryError):
    pass


class GeminiSafetyBlockedError(GeminiPermanentError):
    pass
