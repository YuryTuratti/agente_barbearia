class OpenAIClientError(Exception):
    pass


class OpenAITemporaryError(OpenAIClientError):
    pass


class OpenAIPermanentError(OpenAIClientError):
    pass


class OpenAIInvalidResponseError(OpenAITemporaryError):
    pass
