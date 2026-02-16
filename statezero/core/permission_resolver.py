from typing import Any, Dict, Literal, Optional, Set, Type, Union

from statezero.core.config import AppConfig, Registry, EXTRA_FIELDS_ERROR
from statezero.core.exceptions import PermissionDenied, ValidationError
from statezero.core.interfaces import AbstractORMProvider, AbstractPermission
from statezero.core.types import ActionType, ORMModel


# Map operation type strings to ActionType enum values
_OPERATION_TO_ACTION = {
    "read": ActionType.READ,
    "create": ActionType.CREATE,
    "update": ActionType.UPDATE,
    "delete": ActionType.DELETE,
}


class PermissionResolver:
    """
    Centralised permission resolution for a single request context.

    Caches results per (model, operation_type) so repeated calls within the
    same request are cheap.  No telemetry — callers record that themselves.
    """

    def __init__(
        self,
        request: Any,
        registry: Registry,
        orm_provider: AbstractORMProvider,
    ):
        self.request = request
        self.registry = registry
        self.orm_provider = orm_provider

        # Caches keyed by model class
        self._allowed_actions_cache: Dict[Type, Set[ActionType]] = {}
        # Caches keyed by (model class, operation_type string)
        self._fields_cache: Dict[tuple, Set[str]] = {}

    # ------------------------------------------------------------------
    # Action-level helpers
    # ------------------------------------------------------------------

    def allowed_actions(self, model: Type) -> Set[ActionType]:
        """Union of allowed_actions across all permission classes for *model*."""
        if model in self._allowed_actions_cache:
            return self._allowed_actions_cache[model]

        try:
            model_config = self.registry.get_config(model)
        except (ValueError, KeyError):
            self._allowed_actions_cache[model] = set()
            return set()

        actions: Set[ActionType] = set()
        for permission_cls in model_config.permissions:
            perm: AbstractPermission = permission_cls()
            actions.update(perm.allowed_actions(self.request, model))

        self._allowed_actions_cache[model] = actions
        return actions

    def has_permission(self, model: Type, operation_type: str) -> bool:
        """Does the request have permission for *operation_type* on *model*?"""
        required = _OPERATION_TO_ACTION.get(operation_type, ActionType.READ)
        return required in self.allowed_actions(model)

    def check_actions(
        self, model: Type, requested: Set[ActionType]
    ) -> None:
        """Raise PermissionDenied if any of *requested* actions are disallowed."""
        allowed = self.allowed_actions(model)
        if "__all__" not in allowed and not requested.issubset(allowed):
            missing = requested - allowed
            missing_str = ", ".join(action.value for action in missing)
            raise PermissionDenied(
                f"Missing global permissions for actions: {missing_str}"
            )

    # ------------------------------------------------------------------
    # Queryset-level helpers
    # ------------------------------------------------------------------

    def apply_queryset_permissions(self, model: Type, base_qs: Any) -> Any:
        """
        Apply filter_queryset (OR) then exclude_from_queryset (AND) across
        all registered permission classes for *model*.

        Returns the permission-scoped queryset.
        """
        try:
            model_config = self.registry.get_config(model)
        except (ValueError, KeyError):
            return base_qs

        # Step 1 — filter (OR / additive)
        filtered_querysets = []
        for permission_cls in model_config.permissions:
            perm = permission_cls()
            filtered_querysets.append(perm.filter_queryset(self.request, base_qs))

        if filtered_querysets:
            combined = filtered_querysets[0]
            for qs in filtered_querysets[1:]:
                combined = combined | qs
            base_qs = combined

        # Step 2 — exclude (AND / restrictive)
        for permission_cls in model_config.permissions:
            perm = permission_cls()
            base_qs = perm.exclude_from_queryset(self.request, base_qs)

        return base_qs

    # ------------------------------------------------------------------
    # Field-level helpers
    # ------------------------------------------------------------------

    def get_fields(
        self, model: Type, operation_type: Literal["read", "create", "update"]
    ) -> Set[str]:
        """
        Return the concrete set of field names allowed for *operation_type*
        on *model*.  The ``"__all__"`` sentinel is resolved to the actual
        field set so callers never see it.
        """
        cache_key = (model, operation_type)
        if cache_key in self._fields_cache:
            return self._fields_cache[cache_key]

        try:
            model_config = self.registry.get_config(model)
        except (ValueError, KeyError):
            self._fields_cache[cache_key] = set()
            return set()

        all_fields = self.orm_provider.get_fields(model)
        required_action = _OPERATION_TO_ACTION.get(operation_type)
        allowed_fields: Set[str] = set()

        for permission_cls in model_config.permissions:
            perm: AbstractPermission = permission_cls()

            # Only consider fields from permissions that grant the action
            if required_action and required_action not in perm.allowed_actions(
                self.request, model
            ):
                continue

            if operation_type == "read":
                fields: Union[Set[str], Literal["__all__"]] = perm.visible_fields(
                    self.request, model
                )
            elif operation_type == "create":
                fields = perm.create_fields(self.request, model)
            elif operation_type == "update":
                fields = perm.editable_fields(self.request, model)
            else:
                fields = set()

            if fields == "__all__":
                self._fields_cache[cache_key] = all_fields
                return all_fields

            fields &= all_fields
            allowed_fields |= fields

        self._fields_cache[cache_key] = allowed_fields
        return allowed_fields

    def filter_writable_data(
        self,
        model: Type,
        data: Dict[str, Any],
        create: bool = False,
        extra_fields: str = "ignore",
    ) -> Dict[str, Any]:
        """
        Strip keys from *data* that the user may not write.

        When *create* is True uses ``create_fields``; otherwise
        ``editable_fields``.  Raises ValidationError when
        *extra_fields* == ``"error"`` and unknown keys are present.
        """
        all_fields = self.orm_provider.get_fields(model)

        if extra_fields == EXTRA_FIELDS_ERROR:
            unknown = set(data.keys()) - all_fields
            if unknown:
                raise ValidationError(
                    f"Unknown field(s): {', '.join(sorted(unknown))}. "
                    f"Valid fields are: {', '.join(sorted(all_fields))}"
                )

        op_type = "create" if create else "update"
        allowed = self.get_fields(model, op_type)
        return {k: v for k, v in data.items() if k in allowed}
