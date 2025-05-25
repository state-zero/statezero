import contextvars

# This context variable holds the current operation id.
current_operation_id = contextvars.ContextVar("current_operation_id", default=None)

# This context variable holds whether the current request should create a live subscription
is_live_query = contextvars.ContextVar("is_live_query", default=False)