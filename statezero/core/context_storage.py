import contextvars
from uuid import uuid4
from typing import Any, Optional

# This context variable holds the current operation id (from client headers).
current_operation_id = contextvars.ContextVar("current_operation_id", default=None)

# This context variable holds the canonical id (server-generated for cache sharing).
current_canonical_id = contextvars.ContextVar("current_canonical_id", default=None)


def get_or_create_canonical_id():
    """
    Get the current canonical_id, or generate a new one if it doesn't exist.
    Canonical IDs are used for cross-client cache sharing.

    Returns:
        str: The canonical ID for this request context
    """
    canonical_id = current_canonical_id.get()
    if canonical_id is None:
        canonical_id = str(uuid4())
        current_canonical_id.set(canonical_id)
    return canonical_id