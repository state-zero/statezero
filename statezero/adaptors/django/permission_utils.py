"""
Single source of truth for permission field resolution.

Replaces duplicated permission iteration patterns found across:
- ast_parser._get_operation_fields()
- ast_parser._has_operation_permission()
- process_request._filter_writable_data()
- process_request action check block
- views.FieldPermissionsView._compute_operation_fields()
- orm._get_allowed_fields()
"""
from typing import Any, Dict, List, Literal, Optional, Set, Type, Union

from statezero.core.config import EXTRA_FIELDS_ERROR
from statezero.core.exceptions import PermissionDenied, ValidationError
from statezero.core.interfaces import AbstractPermission
from statezero.core.types import ActionType


# Map operation type strings to ActionType enum values
_OPERATION_TO_ACTION = {
    "read": ActionType.READ,
    "create": ActionType.CREATE,
    "update": ActionType.UPDATE,
    "delete": ActionType.DELETE,
}


def resolve_permission_fields(
    model_config,
    request: Any,
    operation_type: Literal["read", "create", "update"],
    all_fields: Set[str],
) -> Set[str]:
    """
    Single source of truth for 'iterate permissions, collect fields' pattern.

    Iterates over model_config.permissions, collects the field set for the
    given operation type, only from permissions that grant the corresponding
    action.  Returns the union of all permitted fields, intersected with
    all_fields to ensure they actually exist.

    Args:
        model_config: ModelConfig instance (has .permissions list)
        request: The current request for permission context
        operation_type: "read", "create", or "update"
        all_fields: The full set of model fields (used to clamp __all__)

    Returns:
        Set of field names allowed for the operation
    """
    required_action = _OPERATION_TO_ACTION.get(operation_type)
    allowed_fields: Set[str] = set()

    for permission_cls in model_config.permissions:
        perm: AbstractPermission = permission_cls()

        # Only include fields if this permission grants the required action
        if required_action and required_action not in perm.allowed_actions(request, model_config.model):
            continue

        # Get the appropriate field set based on operation
        if operation_type == "read":
            fields: Union[Set[str], Literal["__all__"]] = perm.visible_fields(request, model_config.model)
        elif operation_type == "create":
            fields = perm.create_fields(request, model_config.model)
        elif operation_type == "update":
            fields = perm.editable_fields(request, model_config.model)
        else:
            fields = set()

        if fields == "__all__":
            return set(all_fields)  # Copy so callers can mutate

        fields &= all_fields
        allowed_fields |= fields

    return allowed_fields


def resolve_allowed_actions(
    model_config,
    request: Any,
) -> Set[ActionType]:
    """
    Single source of truth for 'iterate permissions, collect actions' pattern.

    Returns:
        Set of ActionType values the user is allowed to perform on the model.
    """
    allowed: Set[ActionType] = set()
    for permission_cls in model_config.permissions:
        perm: AbstractPermission = permission_cls()
        allowed |= perm.allowed_actions(request, model_config.model)
    return allowed


def has_operation_permission(
    model_config,
    request: Any,
    operation_type: str,
) -> bool:
    """
    Check if the request has permission for the specified operation.

    Args:
        model_config: ModelConfig instance
        request: The current request
        operation_type: "read", "create", "update", or "delete"

    Returns:
        True if the operation is allowed by at least one permission
    """
    required_action = _OPERATION_TO_ACTION.get(operation_type, ActionType.READ)
    return required_action in resolve_allowed_actions(model_config, request)


def check_object_permissions(
    req: Any,
    instance: Any,
    action: ActionType,
    model: Type,
) -> None:
    """
    Check if the given action is allowed on the instance using each permission class.
    Raises PermissionDenied if none of the permissions grant access.
    """
    from statezero.adaptors.django.config import registry
    permissions = registry.get_config(model).permissions
    allowed_obj_actions = set()
    for perm_cls in permissions:
        perm = perm_cls()
        allowed_obj_actions |= perm.allowed_object_actions(req, instance, model)
    if action not in allowed_obj_actions:
        raise PermissionDenied(
            f"Object-level permission denied: Missing {action.value} on object {instance}"
        )


def check_bulk_permissions(
    req: Any,
    items: Any,
    action: ActionType,
    model: Type,
) -> None:
    """
    If the queryset contains one or fewer items, perform individual permission checks.
    Otherwise, loop over permission classes and call bulk_operation_allowed.
    If none allow the bulk operation, raise PermissionDenied.
    """
    from statezero.adaptors.django.config import registry
    permissions = registry.get_config(model).permissions
    if items.count() <= 1:
        for instance in items:
            check_object_permissions(req, instance, action, model)
    else:
        allowed = False
        for perm_cls in permissions:
            perm = perm_cls()
            if perm.bulk_operation_allowed(req, items, action, model):
                allowed = True
                break
        if not allowed:
            raise PermissionDenied(
                f"Bulk {action.value} operation not permitted on queryset"
            )


def filter_writable_data(
    data: Dict[str, Any],
    request: Any,
    model_config,
    all_fields: Set[str],
    create: bool = False,
    extra_fields: str = "ignore",
) -> Dict[str, Any]:
    """
    Single source of truth for stripping disallowed write fields.

    Filters the data dict to only include keys the user has permission to write.

    Args:
        data: The input data dict to filter
        request: The current request
        model_config: ModelConfig instance
        all_fields: The full set of model fields
        create: If True, use create_fields; otherwise use editable_fields
        extra_fields: "ignore" or "error" — controls behavior for unknown fields

    Returns:
        Filtered dict with only allowed keys
    """
    if extra_fields == EXTRA_FIELDS_ERROR:
        unknown_fields = set(data.keys()) - all_fields
        if unknown_fields:
            raise ValidationError(
                f"Unknown field(s): {', '.join(sorted(unknown_fields))}. "
                f"Valid fields are: {', '.join(sorted(all_fields))}"
            )

    operation_type = "create" if create else "update"
    allowed_fields = resolve_permission_fields(model_config, request, operation_type, all_fields)
    return {k: v for k, v in data.items() if k in allowed_fields}
