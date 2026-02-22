from typing import Any, Set, Type, Union, Literal


from statezero.core.interfaces import AbstractPermission
from statezero.core.types import ActionType, ORMModel, RequestType

ALL_ACTIONS = {
    ActionType.CREATE,
    ActionType.READ,
    ActionType.UPDATE,
    ActionType.DELETE,
    ActionType.BULK_CREATE,
}


# A permission class that only allows read operations unless the user is an admin.
class ReadOnlyPermission(AbstractPermission):
    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        return queryset

    def allowed_actions(
        self, request: RequestType, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        return {ActionType.READ}

    def allowed_object_actions(
        self, request, obj, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        return {ActionType.READ}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        if hasattr(request, "user") and request.user.is_superuser:
            return "__all__"
        return set()  # No editable fields for non-admins

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        if hasattr(request, "user") and request.user.is_superuser:
            return "__all__"
        return set()  # No creatable fields for non-admins


# A permission class that restricts which fields can be viewed or edited unless the user is an admin.
class RestrictedFieldsPermission(AbstractPermission):
    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        return queryset

    def allowed_actions(
        self, request: RequestType, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE, ActionType.BULK_CREATE}

    def allowed_object_actions(
        self, request, obj, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE, ActionType.BULK_CREATE}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        if hasattr(request, "user") and request.user.is_superuser:
            return "__all__"
        
        # For ModelWithCustomPKRelation, ensure the related field is included
        if model.__name__ == "ModelWithCustomPKRelation":
            return {"name", "custom_pk", "pk", "custom_pk_related"}
            
        # For other models, keep the original limitation
        return {"name", "custom_pk", "pk"}

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        if hasattr(request, "user") and request.user.is_superuser:
            return "__all__"
        return {"name"}

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        if hasattr(request, "user") and request.user.is_superuser:
            return "__all__"
        return {"name"}


# A permission class that filters objects based on name prefix; admin users get full access.
class NameFilterPermission(AbstractPermission):
    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        return queryset.filter(name__startswith="Allowed")

    def allowed_actions(
        self, request: RequestType, model: Type[ORMModel]
    ) -> Set[ActionType]:
        # For admin, grant all actions.
        if hasattr(request, "user") and request.user.is_superuser:
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        return {
            ActionType.CREATE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.DELETE,
            ActionType.BULK_CREATE,
        }

    def allowed_object_actions(
        self, request, obj, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        if obj.name.startswith("Allowed"):
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        return set()

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"


class NameFilterPermission(AbstractPermission):
    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        # Only return objects with names starting with "Allowed"
        return queryset.filter(name__startswith="Allowed")

    def allowed_actions(
        self, request: RequestType, model: Type[ORMModel]
    ) -> Set[ActionType]:
        # Admin users bypass name filtering and have full access.
        if hasattr(request, "user") and request.user.is_superuser:
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        return {
            ActionType.CREATE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.DELETE,
            ActionType.BULK_CREATE,
        }

    def allowed_object_actions(
        self, request, obj, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        # Only objects with an allowed prefix can be acted upon.
        if obj.name.startswith("Allowed"):
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        return set()

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"


    def get_permission_group_identifier(self, request: RequestType, model: ORMModel) -> str:
        if hasattr(request, "user") and request.user.is_superuser:
            return f"superuser:{request.user.id}"
        return "name_filtered"


# A permission class that filters in bulk_operation_allowed to test pagination bug fix
class FilterInBulkPermission(AbstractPermission):
    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        # Filter by name prefix in filter_queryset
        return queryset.filter(name__startswith="Allowed")

    def bulk_operation_allowed(
        self,
        request: RequestType,
        items: Any,
        action_type: ActionType,
        model: type,
    ) -> bool:
        """
        This method filters the queryset to check bulk permissions.
        This reproduces the bug where if 'items' is already sliced,
        calling .filter() would raise:
        "TypeError: Cannot filter a query once a slice has been taken"
        """
        # Try to filter the queryset - this would fail if items is already sliced
        filtered_count = items.filter(name__startswith="Allowed").count()
        # Allow the operation if we found items matching the filter
        return filtered_count > 0

    def allowed_actions(
        self, request: RequestType, model: Type[ORMModel]
    ) -> Set[ActionType]:
        return {
            ActionType.CREATE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.DELETE,
            ActionType.BULK_CREATE,
        }

    def allowed_object_actions(
        self, request, obj, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if obj.name.startswith("Allowed"):
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
                ActionType.BULK_CREATE,
            }
        return set()

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def get_permission_group_identifier(self, request: RequestType, model: ORMModel) -> str:
        return "filter_in_bulk"


# =============================================================================
# Permission classes for comprehensive client test suite
# =============================================================================

def _is_admin(request):
    return hasattr(request, "user") and request.user.is_superuser


class ReadOnlyItemPermission(AbstractPermission):
    """Non-admin: READ only, no editable/creatable fields."""

    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        if _is_admin(request):
            return ALL_ACTIONS
        return {ActionType.READ}

    def allowed_object_actions(self, request, obj, model):
        if _is_admin(request):
            return ALL_ACTIONS
        return {ActionType.READ}

    def visible_fields(self, request, model):
        return "__all__"

    def editable_fields(self, request, model):
        if _is_admin(request):
            return "__all__"
        return set()

    def create_fields(self, request, model):
        if _is_admin(request):
            return "__all__"
        return set()


class NoDeletePermission(AbstractPermission):
    """Non-admin: CREATE+READ+UPDATE+BULK_CREATE (no DELETE)."""

    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        if _is_admin(request):
            return ALL_ACTIONS
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE, ActionType.BULK_CREATE}

    def allowed_object_actions(self, request, obj, model):
        if _is_admin(request):
            return ALL_ACTIONS
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE, ActionType.BULK_CREATE}

    def visible_fields(self, request, model):
        return "__all__"

    def editable_fields(self, request, model):
        return "__all__"

    def create_fields(self, request, model):
        return "__all__"


class HiddenFieldPermission(AbstractPermission):
    """Non-admin: visible_fields excludes 'secret'."""

    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        return ALL_ACTIONS

    def allowed_object_actions(self, request, obj, model):
        return ALL_ACTIONS

    def visible_fields(self, request, model):
        if _is_admin(request):
            return "__all__"
        # Return all fields except 'secret'
        from statezero.adaptors.django.config import registry
        config = registry.get_config(model)
        all_fields = config.fields if config.fields else set()
        if not all_fields or all_fields == "__all__":
            # Get fields from model
            all_fields = {f.name for f in model._meta.get_fields() if hasattr(f, 'column') or f.name == 'id'}
        return all_fields - {"secret"}

    def editable_fields(self, request, model):
        if _is_admin(request):
            return "__all__"
        return "__all__"

    def create_fields(self, request, model):
        if _is_admin(request):
            return "__all__"
        return "__all__"


class RowFilterPermission(AbstractPermission):
    """Non-admin: filter_queryset to name__startswith='visible'."""

    def filter_queryset(self, request, queryset):
        if _is_admin(request):
            return queryset
        return queryset.filter(name__startswith="visible")

    def allowed_actions(self, request, model):
        return ALL_ACTIONS

    def allowed_object_actions(self, request, obj, model):
        return ALL_ACTIONS

    def visible_fields(self, request, model):
        return "__all__"

    def editable_fields(self, request, model):
        return "__all__"

    def create_fields(self, request, model):
        return "__all__"


class RestrictedCreatePermission(AbstractPermission):
    """Non-admin: create_fields={'name'} only."""

    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        return ALL_ACTIONS

    def allowed_object_actions(self, request, obj, model):
        return ALL_ACTIONS

    def visible_fields(self, request, model):
        return "__all__"

    def editable_fields(self, request, model):
        return "__all__"

    def create_fields(self, request, model):
        if _is_admin(request):
            return "__all__"
        return {"name"}


class RestrictedEditPermission(AbstractPermission):
    """Non-admin: editable_fields={'name'} only."""

    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        return ALL_ACTIONS

    def allowed_object_actions(self, request, obj, model):
        return ALL_ACTIONS

    def visible_fields(self, request, model):
        return "__all__"

    def editable_fields(self, request, model):
        if _is_admin(request):
            return "__all__"
        return {"name"}

    def create_fields(self, request, model):
        return "__all__"


class ExcludeArchivedPermission(AbstractPermission):
    """exclude_from_queryset removes name__startswith='archived'. Applies to ALL users."""

    def filter_queryset(self, request, queryset):
        return queryset

    def exclude_from_queryset(self, request, queryset):
        return queryset.exclude(name__startswith="archived")

    def allowed_actions(self, request, model):
        return ALL_ACTIONS

    def allowed_object_actions(self, request, obj, model):
        return ALL_ACTIONS

    def visible_fields(self, request, model):
        return "__all__"

    def editable_fields(self, request, model):
        return "__all__"

    def create_fields(self, request, model):
        return "__all__"


class ObjectOwnerPermission(AbstractPermission):
    """Object-level: can only update/delete own items (owner == request.user.username)."""

    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        return ALL_ACTIONS

    def allowed_object_actions(self, request, obj, model):
        if _is_admin(request):
            return ALL_ACTIONS
        if hasattr(obj, 'owner') and hasattr(request, 'user') and obj.owner == request.user.username:
            return ALL_ACTIONS
        return {ActionType.READ}

    def visible_fields(self, request, model):
        return "__all__"

    def editable_fields(self, request, model):
        return "__all__"

    def create_fields(self, request, model):
        return "__all__"


class OwnerFilterPerm(AbstractPermission):
    """Filter queryset to owner=request.user.username. Full CRUD on own items."""

    def filter_queryset(self, request, queryset):
        if _is_admin(request):
            return queryset
        if hasattr(request, 'user') and request.user.is_authenticated:
            return queryset.filter(owner=request.user.username)
        return queryset.none()

    def allowed_actions(self, request, model):
        return ALL_ACTIONS

    def allowed_object_actions(self, request, obj, model):
        return ALL_ACTIONS

    def visible_fields(self, request, model):
        return {"id", "name", "value", "owner"}

    def editable_fields(self, request, model):
        return {"name", "value", "owner"}

    def create_fields(self, request, model):
        return {"name", "value", "owner"}


class PublicReadPerm(AbstractPermission):
    """Filter queryset to value__gte=100. Actions=READ only."""

    def filter_queryset(self, request, queryset):
        if _is_admin(request):
            return queryset
        return queryset.filter(value__gte=100)

    def allowed_actions(self, request, model):
        if _is_admin(request):
            return ALL_ACTIONS
        return {ActionType.READ}

    def allowed_object_actions(self, request, obj, model):
        if _is_admin(request):
            return ALL_ACTIONS
        return {ActionType.READ}

    def visible_fields(self, request, model):
        return {"id", "name", "value", "secret"}

    def editable_fields(self, request, model):
        if _is_admin(request):
            return "__all__"
        return set()

    def create_fields(self, request, model):
        if _is_admin(request):
            return "__all__"
        return set()
