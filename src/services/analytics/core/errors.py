class ResultsRepositoryError(Exception):
    """Base class for all ResultsRepository errors."""


class ResultsRepositoryInvalidUrlError(ResultsRepositoryError):
    """Raised when a requested URL is invalid for the repository (e.g., wrong scheme)."""

    def __init__(self, url: str) -> None:
        super().__init__(f"ResultsRepository invalid url: {url}")


class ResultsRepositoryInvalidStoreError(ResultsRepositoryError):
    """Raised when the requested s3:// URL points to a different store than the repository store."""

    def __init__(self, expected_store: str, actual_store: str, url: str) -> None:
        super().__init__(
            f"ResultsRepository invalid store in url (expected={expected_store}, actual={actual_store}): {url}"
        )


class ResultsRepositoryMalformedUrlError(ResultsRepositoryError):
    """Raised when an s3:// URL is syntactically parseable but missing required parts (store/key)."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"ResultsRepository malformed url ({reason}): {url}")
        self.url = url
        self.reason = reason


class ResultsRepositoryStoreMissingError(ResultsRepositoryError):
    """Raised when the configured repository store does not exist."""

    def __init__(self, endpoint: str, store: str) -> None:
        super().__init__(f"ResultsRepository store missing (endpoint={endpoint}, store={store})")
        self.endpoint = endpoint
        self.store = store


class ResultsRepositoryStoreCheckFailedError(ResultsRepositoryError):
    """Raised when checking store existence fails due to an underlying client error."""

    def __init__(self, endpoint: str, store: str, details: str) -> None:
        super().__init__(f"ResultsRepository store check failed (endpoint={endpoint}, store={store}): {details}")
        self.endpoint = endpoint
        self.store = store


class ResultsRepositoryObjectNotFoundError(ResultsRepositoryError):
    """Raised when the requested object key does not exist in the configured store."""

    def __init__(self, endpoint: str, store: str, key: str) -> None:
        super().__init__(f"ResultsRepository object not found (endpoint={endpoint}, store={store}, key={key})")
        self.endpoint = endpoint
        self.store = store
        self.key = key


class ResultsRepositoryObjectDownloadFailedError(ResultsRepositoryError):
    """Raised when downloading an object fails for reasons other than not-found (e.g., network/permission)."""

    def __init__(self, endpoint: str, store: str, key: str, details: str) -> None:
        super().__init__(
            f"ResultsRepository download failed (endpoint={endpoint}, store={store}, key={key}): {details}"
        )
        self.endpoint = endpoint
        self.store = store
        self.key = key


class ResultsRepositoryInvalidZipError(ResultsRepositoryError):
    """Raised when a .zip object is not a valid zip archive."""

    def __init__(self, endpoint: str, store: str, key: str) -> None:
        super().__init__(f"ResultsRepository invalid zip (endpoint={endpoint}, store={store}, key={key})")
        self.endpoint = endpoint
        self.store = store
        self.key = key


class ResultsRepositoryZipHasNoFilesError(ResultsRepositoryError):
    """Raised when a zip archive contains no regular files (only directories or empty)."""

    def __init__(self, endpoint: str, store: str, key: str) -> None:
        super().__init__(f"ResultsRepository zip has no files (endpoint={endpoint}, store={store}, key={key})")
        self.endpoint = endpoint
        self.store = store
        self.key = key


class ResultsRepositoryZipHasMultipleFilesError(ResultsRepositoryError):
    """Raised when a zip archive contains multiple regular files (expected exactly one)."""

    def __init__(self, endpoint: str, store: str, key: str) -> None:
        super().__init__(f"ResultsRepository zip has multiple files (endpoint={endpoint}, store={store}, key={key})")
        self.endpoint = endpoint
        self.store = store
        self.key = key


class ResultsRepositoryResponseCleanupFailedError(ResultsRepositoryError):
    """Raised when closing/releasing the storage response fails."""

    def __init__(self, endpoint: str, store: str, key: str, details: str) -> None:
        super().__init__(
            f"ResultsRepository response cleanup failed (endpoint={endpoint}, store={store}, key={key}): {details}"
        )
        self.endpoint = endpoint
        self.store = store
        self.key = key


class ResultsRepositoryResponseReadFailedError(ResultsRepositoryError):
    """Raised when reading the object response fails (after get_object succeeded)."""

    def __init__(self, endpoint: str, store: str, key: str, details: str) -> None:
        super().__init__(
            f"ResultsRepository response read failed (endpoint={endpoint}, store={store}, key={key}): {details}"
        )
        self.endpoint = endpoint
        self.store = store
        self.key = key
