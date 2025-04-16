from dataclasses import dataclass
from typing import Dict, List, Optional, Union


@dataclass
class ErrorDetail:
    message: str
    code: str

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"ErrorDetail(message={self.message!r}, code={self.code!r})"


class StateZeroError(Exception):
    """Base exception for all StateZero errors."""

    status_code: int = 500
    default_detail: Union[str, Dict, List] = "A server error occurred."
    default_code: str = "error"

    def __init__(
        self,
        detail: Optional[Union[str, Dict, List]] = None,
        code: Optional[str] = None,
    ):
        detail = detail if detail is not None else self.default_detail
        self.detail = self._normalize_detail(detail, code or self.default_code)
        super().__init__(str(self.detail))

    def _normalize_detail(
        self, detail: Union[str, Dict, List], code: Optional[str]
    ) -> Union[ErrorDetail, Dict, List]:
        """Convert details to ErrorDetail objects recursively."""
        if isinstance(detail, str):
            return ErrorDetail(detail, code or self.default_code)
        elif isinstance(detail, dict):
            return {
                key: self._normalize_detail(value, code)
                for key, value in detail.items()
            }
        elif isinstance(detail, list):
            return [self._normalize_detail(item, code) for item in detail]
        return detail


class ValidationError(StateZeroError):
    """Error raised for invalid input. Corresponds to HTTP 400."""

    status_code = 400
    default_detail = "Invalid input."
    default_code = "validation_error"

    def __init__(self, detail: Optional[Union[Dict, List]] = None):
        super().__init__(detail, self.default_code)


class NotFound(StateZeroError):
    """Error raised when an object is not found. Corresponds to HTTP 404."""

    status_code = 404
    default_detail = "Not found."
    default_code = "not_found"

    def __init__(self, detail: Optional[str] = None):
        super().__init__(detail, self.default_code)


class PermissionDenied(StateZeroError):
    """Error raised for permission issues. Corresponds to HTTP 403."""

    status_code = 403
    default_detail = "Permission denied."
    default_code = "permission_denied"

    def __init__(self, detail: Optional[str] = None):
        super().__init__(detail, self.default_code)


class MultipleObjectsReturned(StateZeroError):
    """Error raised when multiple objects are returned but only one was expected."""

    status_code = 400
    default_detail = "Multiple objects returned."
    default_code = "multiple_objects_returned"

    def __init__(self, detail: Optional[str] = None):
        super().__init__(detail, self.default_code)


class ASTValidationError(StateZeroError):
    """Error raised for invalid query syntax (AST issues)."""

    status_code = 400
    default_detail = "Query syntax error."
    default_code = "ast_validation_error"

    def __init__(self, detail: Optional[Union[Dict, List, str]] = None):
        super().__init__(detail, self.default_code)


class ConfigError(Exception):
    """Error raised for configuration issues."""
    pass
