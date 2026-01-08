import inspect
from typing import Dict, Any, Callable, List, Union, Optional
from .interfaces import AbstractActionPermission


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
                permission_list = permissions
            else:
                permission_list = [permissions]

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