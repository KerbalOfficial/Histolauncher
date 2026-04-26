from __future__ import annotations


class DownloadError(Exception):
    pass


class DownloadCancelled(DownloadError):
    def __init__(self, message: str = "Download cancelled by user") -> None:
        super().__init__(message)


class DownloadPaused(DownloadError):
    pass


class DownloadFailed(DownloadError):
    def __init__(self, message: str, *, url: str = "", cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.cause = cause


class HashMismatch(DownloadFailed):
    def __init__(self, path: str, expected: str, actual: str, algo: str = "sha1") -> None:
        super().__init__(
            f"{algo.upper()} mismatch for {path}: expected {expected}, got {actual}"
        )
        self.path = path
        self.expected = expected
        self.actual = actual
        self.algo = algo


__all__ = [
    "DownloadError",
    "DownloadCancelled",
    "DownloadPaused",
    "DownloadFailed",
    "HashMismatch",
]
