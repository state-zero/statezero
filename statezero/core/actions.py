import inspect
import warnings
from typing import Dict, Any, Callable, List, Union, Optional, Type
from .interfaces import AbstractActionPermission


class ValidatedActionPermission:
    """
    Wraps an action permission instance and validates return types match the interface contract.
    Logs warnings for invalid return types (since None is falsy, it fails safe).
    """

    def __init__(self, permission: AbstractActionPermission, cls_name: str):
        self._perm = permission
        self._cls_name = cls_name

    def has_permission(self, request, action_name: str) -> bool:
        result = self._perm.has_permission(request, action_name)
        if not isinstance(result, bool):
            warnings.warn(
                f"{self._cls_name}.has_permission() returned {type(result).__name__}, "
                "but should return a bool. Permission will be denied if falsy.",
                UserWarning,
            )
        return result

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        result = self._perm.has_action_permission(request, action_name, validated_data)
        if not isinstance(result, bool):
            warnings.warn(
                f"{self._cls_name}.has_action_permission() returned {type(result).__name__}, "
                "but should return a bool. Permission will be denied if falsy.",
                UserWarning,
            )
        return result


def _make_validated_action_permission_class(perm_class: Type[AbstractActionPermission]) -> Type:
    """
    Creates a wrapper class that returns ValidatedActionPermission instances when instantiated.
    """
    class ValidatedActionPermissionClass:
        def __new__(cls, *args, **kwargs):
            instance = perm_class(*args, **kwargs)
            return ValidatedActionPermission(instance, perm_class.__name__)

    ValidatedActionPermissionClass.__name__ = f"Validated{perm_class.__name__}"
    ValidatedActionPermissionClass.__qualname__ = f"Validated{perm_class.__qualname__}"

    return ValidatedActionPermissionClass


def _make_validated_action_permission_instance(perm_instance: AbstractActionPermission):
    """
    Wraps an existing permission instance (e.g. AnyOf/AllOf) so it can be
    used in the same slot as a permission class.  The views layer calls
    ``permission_class()`` — this wrapper returns the ValidatedActionPermission
    when called.
    """
    cls_name = type(perm_instance).__name__
    validated = ValidatedActionPermission(perm_instance, cls_name)

    class ValidatedInstanceWrapper:
        def __new__(cls, *args, **kwargs):
            return validated

    ValidatedInstanceWrapper.__name__ = f"Validated{cls_name}"
    ValidatedInstanceWrapper.__qualname__ = f"Validated{cls_name}"

    return ValidatedInstanceWrapper


class ActionRegistry:
    """Framework-agnostic action registry"""

    def __init__(self):
        self._actions: Dict[str, Dict] = {}

    def register(
        self,
        func: Callable = None,
        *,
        docstring: Optional[str] = None,
        serializer=None,
        response_serializer=None,
        permissions: Union[
            List[AbstractActionPermission], AbstractActionPermission, None
        ] = None,
        name: Optional[str] = None,
        display: Optional[Any] = None,
    ):
        """Register an action function with an optional, explicit docstring and display metadata."""

        def decorator(func: Callable):
            action_name = name or func.__name__

            # Determine the docstring, prioritizing the explicit parameter over the function's own.
            final_docstring = docstring or func.__doc__
            if final_docstring:
                # Clean up indentation and whitespace from the docstring.
                final_docstring = inspect.cleandoc(final_docstring)

            if permissions is None:
                permission_list = []
            elif isinstance(permissions, list):
                permission_list = [
                    _make_validated_action_permission_instance(p)
                    if isinstance(p, AbstractActionPermission)
                    else _make_validated_action_permission_class(p)
                    for p in permissions
                ]
            else:
                if isinstance(permissions, AbstractActionPermission):
                    permission_list = [_make_validated_action_permission_instance(permissions)]
                else:
                    permission_list = [_make_validated_action_permission_class(permissions)]

            self._actions[action_name] = {
                "function": func,
                "serializer": serializer,
                "response_serializer": response_serializer,
                "permissions": permission_list,
                "name": action_name,
                "module": func.__module__,
                "docstring": final_docstring,  # Store the determined docstring
                "display": display,  # Store display metadata
            }

            # Mark the function with attributes for external detection
            # (e.g., django-ai-first can detect and use as LLM tools)
            func._statezero_action = True
            func._statezero_action_name = action_name
            func._statezero_serializer = serializer
            func._statezero_response_serializer = response_serializer
            func._statezero_permissions = permission_list

            return func

        if func is None:
            return decorator
        return decorator(func)

    def get_actions(self) -> Dict[str, Dict]:
        return self._actions

    def get_action(self, name: str) -> Optional[Dict]:
        return self._actions.get(name)


# Global registry instance
action_registry = ActionRegistry()


# Convenient decorator
def action(
    func: Callable = None,
    *,
    docstring: Optional[str] = None,
    serializer=None,
    response_serializer=None,
    permissions: Union[
        List[AbstractActionPermission], AbstractActionPermission, None
    ] = None,
    name: Optional[str] = None,
    display: Optional[Any] = None,
):
    """Framework-agnostic decorator to register an action with optional display metadata."""
    return action_registry.register(
        func,
        docstring=docstring,
        serializer=serializer,
        response_serializer=response_serializer,
        permissions=permissions,
        name=name,
        display=display,
    )