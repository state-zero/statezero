import logging
from typing import Any, Set, Type

from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils.module_loading import import_string
from rest_framework.permissions import AllowAny, BasePermission


from statezero.core.interfaces import AbstractPermission
from statezero.core.types import ActionType, ORMModel, RequestType

logger = logging.getLogger(__name__)

User = get_user_model()

class AllowAllPermission(AbstractPermission):
    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        return queryset

    def allowed_actions(self, request: RequestType, model: Type[ORMModel]) -> Set[ActionType]:  # type: ignore
        return {
            ActionType.CREATE,
            ActionType.DELETE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.BULK_CREATE,
        }

    def allowed_object_actions(self, request, obj, model: Type[ORMModel]) -> Set[ActionType]:  # type: ignore
        return {
            ActionType.CREATE,
            ActionType.DELETE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.BULK_CREATE,
        }
    
    def _get_user_fields(self) -> Set[str]:
        return {"id", "username"}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        if model is User:
            return self._get_user_fields()
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        if model is User:
            return self._get_user_fields()
        return "__all__"

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        if model is User:
            return self._get_user_fields()
        return "__all__"

class IsAuthenticatedPermission(AbstractPermission):
    """
    Permission class that allows access only to authenticated users.
    If the user is not authenticated, the queryset is emptied and no actions or fields are allowed.
    """

    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        if not request.user.is_authenticated:
            return queryset.none()
        return queryset

    def allowed_actions(
        self, request: RequestType, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if not request.user.is_authenticated:
            return set()
        return {
            ActionType.CREATE,
            ActionType.DELETE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.BULK_CREATE,
        }

    def allowed_object_actions(
        self, request, obj, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if not request.user.is_authenticated:
            return set()
        return {
            ActionType.CREATE,
            ActionType.DELETE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.BULK_CREATE,
        }
    
    def _get_user_fields(self) -> Set[str]:
        return {"id", "username"}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        if not request.user.is_authenticated:
            return set()
        if model is User:
            return self._get_user_fields()
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        if not request.user.is_authenticated:
            return set()
        if model is User:
            return self._get_user_fields()
        return "__all__"

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        if not request.user.is_authenticated:
            return set()
        if model is User:
            return self._get_user_fields()
        return "__all__"


class IsStaffPermission(AbstractPermission):
    """
    Permission class that allows access only to staff users.
    The user must be both authenticated and marked as staff. Otherwise, access is denied.
    """

    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        if not (request.user.is_authenticated and request.user.is_staff):
            return queryset.none()
        return queryset

    def allowed_actions(
        self, request: RequestType, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if not (request.user.is_authenticated and request.user.is_staff):
            return set()
        return {
            ActionType.CREATE,
            ActionType.DELETE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.BULK_CREATE,
        }

    def allowed_object_actions(
        self, request, obj, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if not (request.user.is_authenticated and request.user.is_staff):
            return set()
        return {
            ActionType.CREATE,
            ActionType.DELETE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.BULK_CREATE,
        }
    
    def _get_user_fields(self) -> Set[str]:
        return {"id", "username", "email", "first_name", "last_name"}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        if not (request.user.is_authenticated and request.user.is_staff):
            return set()
        if model is User:
            return self._get_user_fields()
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        if not (request.user.is_authenticated and request.user.is_staff):
            return set()
        if model is User:
            return self._get_user_fields()
        return "__all__"

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        if not (request.user.is_authenticated and request.user.is_staff):
            return set()
        if model is User:
            return self._get_user_fields()
        return "__all__"


class ORMBridgeViewAccessGate(BasePermission):
    """
    Gate access only for ModelList and schema endpoints.
    In local dev (DEBUG=True), optionally set a default user if provided.
    If no default user is provided or an error occurs, set the user to AnonymousUser
    and return has_permission = True.
    In production, strictly use the configured permission class.

    For schema endpoints (models/, get-schema/, actions-schema/), a sync token
    can be used to allow access in production without authentication. Set
    STATEZERO_SYNC_TOKEN in settings and pass the token via X-Sync-Token header.
    """

    def __init__(self):
        access_class_path = getattr(
            settings,
            "STATEZERO_VIEW_ACCESS_CLASS",
            "rest_framework.permissions.AllowAny",
        )
        try:
            self.view_access = import_string(access_class_path)()
            logger.debug("Using view access class: %s", access_class_path)
        except Exception as e:
            logger.error(
                "Error importing view access class '%s': %s", access_class_path, str(e)
            )
            self.view_access = AllowAny()

    def _is_schema_endpoint(self, path: str) -> bool:
        """Check if the request path is a schema endpoint."""
        return (
            path.endswith('/models/') or
            path.endswith('/get-schema/') or
            path.endswith('/actions-schema/')
        )

    def _check_sync_token(self, request) -> bool:
        """
        Check if a valid sync token is provided in the request headers.
        Returns True if the token is configured and matches, False otherwise.
        """
        sync_token = getattr(settings, 'STATEZERO_SYNC_TOKEN', None)
        if not sync_token:
            return False

        provided_token = request.headers.get('X-Sync-Token')
        if provided_token and provided_token == sync_token:
            logger.debug("Valid sync token provided for schema endpoint")
            return True

        return False

    def has_permission(self, request, view):
        logger.debug("Evaluating has_permission for path: %s", request.path)

        # Only apply custom access for schema and model list endpoints.
        if request.path.startswith("/statezero/"):
            logger.debug("Path matches statezero endpoints. DEBUG=%s", settings.DEBUG)

            # Check for sync token on schema endpoints (works in both DEBUG and production)
            if self._is_schema_endpoint(request.path) and self._check_sync_token(request):
                logger.debug("Sync token validated, allowing access to schema endpoint")
                # Set anonymous user for sync token requests
                request.user = AnonymousUser()
                # Mark request as sync token authenticated to bypass model permissions in process_schema
                request._statezero_sync_token_access = True
                return True

            if settings.DEBUG:
                # In development mode, try to set a default user if one is provided.
                default_user_func_path = getattr(
                    settings, "STATEZERO_DEFAULT_USER_FUNC", None
                )
                if default_user_func_path:
                    logger.debug(
                        "Default user function specified: %s", default_user_func_path
                    )
                    try:
                        default_user_func = import_string(default_user_func_path)
                        request.user = default_user_func(request)
                        logger.debug("Default user set to: %s", request.user)
                    except Exception as e:
                        logger.error(
                            "Error setting default user using '%s': %s",
                            default_user_func_path,
                            str(e),
                        )
                        request.user = AnonymousUser()
                else:
                    logger.debug(
                        "No default user function specified; setting user to AnonymousUser"
                    )
                    request.user = AnonymousUser()
                logger.debug(
                    "Returning True for DEBUG mode on endpoint: %s", request.path
                )
                return True
            else:
                # In production, strictly use the configured permission class.
                logger.debug(
                    "Production mode: delegating permission check to %s",
                    self.view_access.__class__.__name__,
                )
                permission = self.view_access.has_permission(request, view)
                logger.debug("Production mode permission result: %s", permission)
                return permission

        # For endpoints outside our gate's scope, delegate to the default permission logic.
        logger.debug(
            "Path does not match statezero endpoints; delegating permission check to %s",
            self.view_access.__class__.__name__,
        )
        permission = self.view_access.has_permission(request, view)
        logger.debug("Non-statezero endpoint permission result: %s", permission)
        return permission
