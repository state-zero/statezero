from statezero.core.interfaces import AbstractActionPermission


class AnyOf(AbstractActionPermission):
    """OR compositor — passes if ANY child permission passes."""

    def __init__(self, *permissions):
        self._permissions = permissions

    def _iter(self):
        for p in self._permissions:
            if isinstance(p, AbstractActionPermission):
                yield p
            else:
                yield p()

    def has_permission(self, request, action_name: str) -> bool:
        children = list(self._iter())
        if not children:
            return False
        return any(p.has_permission(request, action_name) for p in children)

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        children = list(self._iter())
        if not children:
            return False
        return any(p.has_action_permission(request, action_name, validated_data) for p in children)


class AllOf(AbstractActionPermission):
    """AND compositor — passes only if ALL child permissions pass."""

    def __init__(self, *permissions):
        self._permissions = permissions

    def _iter(self):
        for p in self._permissions:
            if isinstance(p, AbstractActionPermission):
                yield p
            else:
                yield p()

    def has_permission(self, request, action_name: str) -> bool:
        children = list(self._iter())
        if not children:
            return False
        return all(p.has_permission(request, action_name) for p in children)

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        children = list(self._iter())
        if not children:
            return False
        return all(p.has_action_permission(request, action_name, validated_data) for p in children)
