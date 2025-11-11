from django.utils.deprecation import MiddlewareMixin

from statezero.core.context_storage import current_operation_id, current_canonical_id


class OperationIDMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # The header in Django is available via request.META (HTTP headers are prefixed with HTTP_)
        op_id = request.META.get("HTTP_X_OPERATION_ID")
        current_operation_id.set(op_id)

        # Also read canonical_id from headers if provided by client
        canonical_id = request.META.get("HTTP_X_CANONICAL_ID")
        if canonical_id:
            current_canonical_id.set(canonical_id)