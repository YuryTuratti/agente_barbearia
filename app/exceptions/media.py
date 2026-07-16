class MediaProcessingError(Exception):
    pass


class MediaTemporaryError(MediaProcessingError):
    pass


class MediaPermanentError(MediaProcessingError):
    pass


class MediaTooLargeError(MediaPermanentError):
    pass


class InvalidMediaError(MediaPermanentError):
    pass


class UnsupportedMediaTypeError(MediaPermanentError):
    pass
