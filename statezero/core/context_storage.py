import contextvars

# This context variable holds the current operation id.
current_operation_id = contextvars.ContextVar("current_operation_id", default=None)

# This stores the semantic hash of the queryset that did the operation
queryset_semantic_hash = contextvars.ContextVar("queryset_semantic_hash", default=None)