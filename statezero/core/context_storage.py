import contextvars
from typing import Any, Optional

# This context variable holds the current operation id (from client headers).
current_operation_id = contextvars.ContextVar("current_operation_id", default=None)

# This context variable holds the canonical id (server-generated for cache sharing).
current_canonical_id = contextvars.ContextVar("current_canonical_id", default=None)
