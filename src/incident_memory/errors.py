"""Application errors that can be translated into safe API responses."""

from typing import Any


class ApplicationError(Exception):
    """Base class for expected application failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class ValidationError(ApplicationError):
    """Raised when an API request fails validation."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            code="validation_error",
            status_code=400,
            details=details,
        )


class DependencyUnavailableError(ApplicationError):
    """Raised when a live adapter has not been configured or is unavailable."""

    def __init__(self, dependency: str) -> None:
        super().__init__(
            f"The {dependency} adapter is not configured in this scaffold.",
            code="dependency_unavailable",
            status_code=503,
            details={"dependency": dependency},
        )


class AdapterContractError(ApplicationError):
    """Raised when an adapter violates an application port contract."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="adapter_contract_error",
            status_code=502,
        )
