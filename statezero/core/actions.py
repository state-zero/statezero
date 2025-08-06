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
        serializer=None,
        response_serializer=None,
        permissions: Union[
            List[AbstractActionPermission], AbstractActionPermission, None
        ] = None,
        name: Optional[str] = None,
    ):
        """Register an action function with optional serializers and permissions"""

        def decorator(func: Callable):
            action_name = name or func.__name__

            # Normalize permissions to list
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
                "app": None,
            }
            return func

        if func is None:
            return decorator
        return decorator(func)

    def get_actions(self) -> Dict[str, Dict]:
        """Get all registered actions"""
        return self._actions

    def get_action(self, name: str) -> Optional[Dict]:
        """Get a specific action by name"""
        return self._actions.get(name)


# Global registry instance
action_registry = ActionRegistry()


# Convenient decorator
def action(
    func: Callable = None,
    *,
    serializer=None,
    response_serializer=None,
    permissions: Union[
        List[AbstractActionPermission], AbstractActionPermission, None
    ] = None,
    name: Optional[str] = None,
):
    """Framework-agnostic decorator to register an action"""
    return action_registry.register(
        func,
        serializer=serializer,
        response_serializer=response_serializer,
        permissions=permissions,
        name=name,
    )