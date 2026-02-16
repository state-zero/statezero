"""
Per-request permission resolver with caching.

Wraps permission_utils functions so that repeated calls for the same model
within a single request hit a cache instead of re-iterating permission classes.
"""
from typing import Any, Dict, Set, Type

from statezero.core.config import ModelConfig, Registry, EXTRA_FIELDS_ERROR
from statezero.core.exceptions import PermissionDenied, ValidationError
from statezero.core.interfaces import AbstractORMProvider
from statezero.core.types import ActionType


class PermissionResolver:
    """Centralised, cached permission resolution for a single request."""

    def __init__(self, request: Any, registry: Registry, orm_provider: AbstractORMProvider):
        self.request = request
        self.registry = registry
        self.orm_provider = orm_provider
        self._actions_cache: Dict[Type, Set[ActionType]] = {}
        self._fields_cache: Dict[tuple, Set[str]] = {}  # (model, op_type) -> Set[str]

    # ------------------------------------------------------------------
    # Cached helpers
    # ------------------------------------------------------------------

    def allowed_actions(self, model: Type) -> Set[ActionType]:
        """Cached union of allowed_actions across all permission classes."""
        if model not in self._actions_cache:
            from statezero.adaptors.django.permission_utils import resolve_allowed_actions
            model_config = self.registry.get_config(model)
            self._actions_cache[model] = resolve_allowed_actions(model_config, self.request)
        return self._actions_cache[model]

    def permitted_fields(self, model: Type, operation_type: str) -> Set[str]:
        """Cached field set for an operation. Empty set = no permission."""
        key = (model, operation_type)
        if key not in self._fields_cache:
            from statezero.adaptors.django.permission_utils import (
                has_operation_permission,
                resolve_permission_fields,
            )
            try:
                model_config = self.registry.get_config(model)
                if not has_operation_permission(model_config, self.request, operation_type):
                    self._fields_cache[key] = set()
                else:
                    all_fields = self.orm_provider.get_fields(model)
                    self._fields_cache[key] = resolve_permission_fields(
                        model_config, self.request, operation_type, all_fields,
                    )
            except (ValueError, KeyError):
                self._fields_cache[key] = set()
        return self._fields_cache[key]

    def has_permission(self, model: Type, operation_type: str) -> bool:
        """Check if operation is allowed (uses actions cache)."""
        from statezero.adaptors.django.permission_utils import _OPERATION_TO_ACTION
        required_action = _OPERATION_TO_ACTION.get(operation_type, ActionType.READ)
        return required_action in self.allowed_actions(model)

    # ------------------------------------------------------------------
    # Queryset-level permissions
    # ------------------------------------------------------------------

    def apply_queryset_permissions(self, model: Type, base_queryset: Any) -> Any:
        """Apply filter_queryset (OR) + exclude_from_queryset (AND)."""
        model_config = self.registry.get_config(model)

        # Step 1: filter_queryset with OR logic (additive permissions)
        filtered_querysets = []
        for permission_cls in model_config.permissions:
            perm = permission_cls()
            filtered_qs = perm.filter_queryset(self.request, base_queryset)
            filtered_querysets.append(filtered_qs)

        if filtered_querysets:
            combined = filtered_querysets[0]
            for qs in filtered_querysets[1:]:
                combined = combined | qs
            base_queryset = combined

        # Step 2: exclude_from_queryset with AND logic (restrictive)
        for permission_cls in model_config.permissions:
            perm = permission_cls()
            base_queryset = perm.exclude_from_queryset(self.request, base_queryset)

        return base_queryset

    # ------------------------------------------------------------------
    # Object / bulk permission checks
    # ------------------------------------------------------------------

    def check_object_permissions(self, instance: Any, action: ActionType, model: Type) -> None:
        """Delegates to permission_utils.check_object_permissions."""
        from statezero.adaptors.django.permission_utils import check_object_permissions
        check_object_permissions(self.request, instance, action, model)

    def check_bulk_permissions(self, queryset: Any, action: ActionType, model: Type) -> None:
        """Delegates to permission_utils.check_bulk_permissions."""
        from statezero.adaptors.django.permission_utils import check_bulk_permissions
        check_bulk_permissions(self.request, queryset, action, model)

    # ------------------------------------------------------------------
    # Writable-data filtering
    # ------------------------------------------------------------------

    def filter_writable_data(
        self,
        model: Type,
        data: Dict[str, Any],
        create: bool = False,
        extra_fields: str = "ignore",
    ) -> Dict[str, Any]:
        """Filter data dict to only writable fields (uses cache)."""
        all_fields = self.orm_provider.get_fields(model)

        if extra_fields == EXTRA_FIELDS_ERROR:
            unknown = set(data.keys()) - all_fields
            if unknown:
                raise ValidationError(
                    f"Unknown field(s): {', '.join(sorted(unknown))}. "
                    f"Valid fields are: {', '.join(sorted(all_fields))}"
                )

        operation_type = "create" if create else "update"
        allowed = self.permitted_fields(model, operation_type)
        return {k: v for k, v in data.items() if k in allowed}
