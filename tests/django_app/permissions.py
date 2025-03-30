from typing import Any, Set, Type


from statezero.core.interfaces import AbstractPermission
from statezero.core.types import ActionType, ORMModel, RequestType


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
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"
