"""Custom exceptions for Octavia LoxiLB Provider Driver."""


class LoxiLBDriverException(Exception):
    """Base exception for all LoxiLB driver exceptions."""

    def __init__(self, message: str = "An unknown LoxiLB driver error occurred"):
        self.message = message
        super().__init__(self.message)


class LoxiLBConfigurationException(LoxiLBDriverException):
    """Raised when configuration is invalid or missing."""

    def __init__(self, key: str, value: str = "", reason: str = ""):
        self.key = key
        self.value = value
        self.reason = reason
        message = f"Invalid configuration for '{key}' (value: '{value}'): {reason}"
        super().__init__(message)


class LoxiLBAPIException(LoxiLBDriverException):
    """Raised when an API request to LoxiLB fails."""

    def __init__(
        self,
        message: str = "LoxiLB API request failed",
        status_code: int = 0,
        response_body: str = "",
        endpoint: str = "",
    ):
        self.status_code = status_code
        self.response_body = response_body
        self.endpoint = endpoint
        full_msg = f"{message} (endpoint: {endpoint}, status: {status_code}, response: {response_body})"
        super().__init__(full_msg)


class LoxiLBConnectionException(LoxiLBAPIException):
    """Raised when connection to LoxiLB cannot be established."""

    def __init__(self, endpoint: str, original_exception: str = ""):
        super().__init__(
            message=f"Failed to connect to LoxiLB at {endpoint}: {original_exception}",
            endpoint=endpoint,
        )


class LoxiLBTimeoutException(LoxiLBAPIException):
    """Raised when a request to LoxiLB times out."""

    def __init__(self, endpoint: str, timeout_value: float, operation: str = ""):
        super().__init__(
            message=f"Operation '{operation}' timed out after {timeout_value}s on {endpoint}",
            endpoint=endpoint,
        )


class LoxiLBNotFoundException(LoxiLBAPIException):
    """Raised when a requested resource is not found in LoxiLB."""

    def __init__(self, resource_type: str, resource_id: str, endpoint: str = ""):
        super().__init__(
            message=f"{resource_type} '{resource_id}' not found",
            status_code=404,
            endpoint=endpoint,
        )


class LoxiLBConflictException(LoxiLBAPIException):
    """Raised when a resource conflict occurs in LoxiLB."""

    def __init__(self, resource_type: str, resource_id: str, conflict_reason: str = ""):
        super().__init__(
            message=f"Conflict for {resource_type} '{resource_id}': {conflict_reason}",
            status_code=409,
        )


class LoxiLBAuthenticationException(LoxiLBAPIException):
    """Raised when authentication to LoxiLB fails."""

    def __init__(self, endpoint: str, auth_type: str):
        super().__init__(
            message=f"Authentication failed for {endpoint} using auth_type '{auth_type}'",
            status_code=401,
            endpoint=endpoint,
        )


class LoxiLBTranslationError(LoxiLBDriverException):
    """Raised when translation from Octavia models to LoxiLB models fails."""

    def __init__(self, resource: str, reason: str):
        super().__init__(f"Failed to translate {resource}: {reason}")
