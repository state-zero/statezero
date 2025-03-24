from typing import Any, Set, Type

from ormbridge.core.constants import ALL_FIELDS
from ormbridge.core.interfaces import AbstractPermission
from ormbridge.core.types import ActionType, ORMModel, RequestType


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
            }
        return {ActionType.READ}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {ALL_FIELDS}
        return set()  # No editable fields for non-admins

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {ALL_FIELDS}
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
            }
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE}

    def allowed_object_actions(
        self, request, obj, model: Type[ORMModel]
    ) -> Set[ActionType]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
            }
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        # Only allow seeing the name and id fields
        return {"name", "custom_pk", "pk"}

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {ALL_FIELDS}
        return {"name"}

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        if hasattr(request, "user") and request.user.is_superuser:
            return {ALL_FIELDS}
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
            }
        return {
            ActionType.CREATE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.DELETE,
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
            }
        if obj.name.startswith("Allowed"):
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
            }
        return set()

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}


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
            }
        return {
            ActionType.CREATE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.DELETE,
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
            }
        # Only objects with an allowed prefix can be acted upon.
        if obj.name.startswith("Allowed"):
            return {
                ActionType.CREATE,
                ActionType.READ,
                ActionType.UPDATE,
                ActionType.DELETE,
            }
        return set()

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}

class CustomIntersectionPermission(AbstractPermission):
    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        return queryset

    def allowed_actions(self, request: RequestType, model: Type) -> Set[ActionType]:
        # Allow only a subset of actions (for example, no DELETE)
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE}

    def allowed_object_actions(self, request, obj, model: Type) -> Set[ActionType]:
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        # Return a limited set of fields per model name.
        model_name = model.__name__
        if model_name == "ParentTestModel":
            # For ParentTestModel, permit "name", "description" and "children"
            return {"name", "description", "children"}
        elif model_name == "ChildTestModel":
            # For ChildTestModel, only "name" and "extra" are allowed
            return {"name", "extra"}
        elif model_name == "GrandChildTestModel":
            # For GrandChildTestModel, allow "name" and "detail"
            return {"name", "detail"}
        return {"id"}

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return self.visible_fields(request, model)

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return self.visible_fields(request, model)