import contextvars

# This context variable holds the current operation id.
current_operation_id = contextvars.ContextVar("current_operation_id", default=None)