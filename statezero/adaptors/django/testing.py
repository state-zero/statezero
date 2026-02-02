"""
Test-only helpers for StateZero Django integration.

Opt-in usage (in your Django project test settings):

MIDDLEWARE = [
    # ...
    "statezero.adaptors.django.testing.TestSeedingMiddleware",
    # ...
]

Then send:
- X-TEST-SEEDING: 1 to temporarily bypass model permissions for that request.
- X-TEST-RESET: 1 to purge all registered StateZero models for that request.

Set STATEZERO_TEST_MODE = True in settings to enable.
"""

from contextlib import contextmanager

from django.conf import settings
from django.utils.module_loading import import_string

from statezero.adaptors.django.config import registry, config
from statezero.adaptors.django.permissions import AllowAllPermission

class AllowAllFieldsPermission(AllowAllPermission):
    def visible_fields(self, request, model):
        return "__all__"

    def editable_fields(self, request, model):
        return "__all__"

    def create_fields(self, request, model):
        return "__all__"



def _is_truthy_header(request, header_name: str) -> bool:
    header_value = request.headers.get(header_name)
    return str(header_value or "").lower() in {"1", "true", "yes", "on"}


def _is_test_mode_enabled() -> bool:
    return bool(getattr(settings, "STATEZERO_TEST_MODE", False))


def _is_test_seeding_request(request) -> bool:
    if not _is_test_mode_enabled():
        return False
    return _is_truthy_header(request, "X-TEST-SEEDING")




def _test_seeding_fields_all(request) -> bool:
    return _is_truthy_header(request, "X-TEST-SEEDING-FIELDS")

def _is_test_reset_request(request) -> bool:
    if not _is_test_mode_enabled():
        return False
    return _is_truthy_header(request, "X-TEST-RESET")


def _get_request_context_manager(request):
    """
    Optional hook for wrapping requests in a custom context manager.

    Set STATEZERO_TEST_REQUEST_CONTEXT to a dotted path of a callable that
    accepts (request) and returns a context manager.
    """
    path = getattr(settings, "STATEZERO_TEST_REQUEST_CONTEXT", None)
    if not path:
        return _noop_context()
    factory = import_string(path)
    ctx = factory(request)
    return ctx if ctx is not None else _noop_context()


@contextmanager
def _temporary_allow_all_permissions(permission_class=AllowAllPermission):
    original_permissions = {}
    try:
        for model, model_config in registry._models_config.items():
            original_permissions[model] = model_config._permissions
            model_config._permissions = [permission_class]
        yield
    finally:
        for model, perms in original_permissions.items():
            if model in registry._models_config:
                registry._models_config[model]._permissions = perms


@contextmanager
def _temporary_silent_events():
    event_bus = getattr(config, "event_bus", None)
    if not event_bus or not getattr(event_bus, "broadcast_emitter", None):
        yield
        return

    original_emitter = event_bus.broadcast_emitter

    class _SilentEmitter:
        def emit(self, *args, **kwargs):
            return None

    try:
        event_bus.broadcast_emitter = _SilentEmitter()
        yield
    finally:
        event_bus.broadcast_emitter = original_emitter


@contextmanager
def _noop_context():
    yield


def _purge_registered_models():
    # Delete all registered StateZero models, in reverse registration order.
    # This avoids FK constraints in most cases (children deleted before parents).
    models = list(registry._models_config.keys())
    for model in reversed(models):
        model.objects.all().delete()


class TestSeedingMiddleware:
    """
    Test-only middleware that allows a request to bypass model permissions
    when X-TEST-SEEDING is present and STATEZERO_TEST_MODE is enabled.

    It also silences StateZero event emissions during the request unless
    STATEZERO_TEST_SEEDING_SILENT is set to False.

    X-TEST-RESET purges all registered StateZero models for the request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not _is_test_mode_enabled():
            return self.get_response(request)

        with _get_request_context_manager(request):
            if _is_test_reset_request(request):
                _purge_registered_models()

            if not _is_test_seeding_request(request):
                return self.get_response(request)

            silent = getattr(settings, "STATEZERO_TEST_SEEDING_SILENT", True)
            permission_class = AllowAllFieldsPermission if _test_seeding_fields_all(request) else AllowAllPermission
            event_ctx = _temporary_silent_events() if silent else _noop_context()

            with _temporary_allow_all_permissions(permission_class), event_ctx:
                return self.get_response(request)
