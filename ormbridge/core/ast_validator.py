from enum import Enum
from typing import Any, Callable, Dict, List, Set, Type

import networkx as nx

from ormbridge.core.config import Registry

from ormbridge.core.exceptions import PermissionDenied
from ormbridge.core.interfaces import AbstractPermission
from ormbridge.core.types import ActionType, ORMModel, RequestType

class ASTValidator:
    def __init__(
        self,
        model_graph: nx.DiGraph,
        get_model_name: Callable[[Type], str],
        registry: Registry,
        request: Any,
        get_model_by_name: Callable[[str], Type],
    ):
        """
        :param model_graph: The model graph built by the ORM's graph builder.
        :param get_model_name: A callable that returns a unique name for a given model.
        :param registry: Global registry mapping models to their ModelConfig.
        :param request: The current request (for permission checking).
        :param get_model_by_name: Helper to resolve a model by its unique name.
        """
        self.model_graph = model_graph
        self.get_model_name = get_model_name
        self.registry = registry
        self.request = request
        self.get_model_by_name = get_model_by_name

    def _aggregate_permission_instances(self, model: Type) -> List[AbstractPermission]:
        """
        Given a model, return a list of permission instances as specified in its ModelConfig.
        (You might cache these or use a more sophisticated composition in a real app.)
        """
        config = self.registry.get_config(model)
        # Instantiate each permission class (assuming no extra init parameters).
        return [perm_class() for perm_class in config.permissions]

    def _allowed_fields_for_model(self, model: Type) -> Set[str]:
        """
        Aggregates the visible fields from all permission instances for the given model.
        """
        allowed_fields: Set[str] = set()
        for perm in self._aggregate_permission_instances(model):
            allowed_fields |= perm.visible_fields(self.request, model)
        return allowed_fields

    def _has_read_permission(self, model: Type) -> bool:
        """
        Checks if any of the permission instances for the model allow the READ action.
        """
        for perm in self._aggregate_permission_instances(model):
            if ActionType.READ in perm.allowed_actions(self.request, model):
                return True
        return False

    def is_field_allowed(self, model: Type, field_path: str) -> bool:
        """
        Validates a nested field path (e.g. "related__name" or "level2__level3__name")
        by using the model registry to extract the permission settings for each model
        encountered along the path. Uses "__" to separate nested fields, and "::" as
        the delimiter within a field node key.
        """
        parts = field_path.split("__")
        current_model = model
        current_model_name = self.get_model_name(current_model)

        # Check that the user has READ permission on the root model.
        if not self._has_read_permission(current_model):
            return False

        # Get allowed fields from permission settings.
        allowed = self._allowed_fields_for_model(current_model)
        for part in parts:
            # Check that the field is allowed on the current model.
            if part not in allowed and "__all__" not in allowed:
                return False

            # Construct the field node key.
            field_node = f"{current_model_name}::{part}"
            if self.model_graph.has_node(field_node):
                node_data = self.model_graph.nodes[field_node].get("data")
                if not node_data:
                    return False
                if node_data.is_relation:
                    # If this is a relation, resolve the related model.
                    related_model_name = node_data.related_model
                    if related_model_name:
                        related_model = self.get_model_by_name(related_model_name)
                        # Check READ permission on the related model.
                        if not self._has_read_permission(related_model):
                            return False
                        # Move to the related model for the next part.
                        current_model = related_model
                        current_model_name = related_model_name
                        allowed = self._allowed_fields_for_model(current_model)
                        continue
                    else:
                        return False
                else:
                    # Terminal (non-relation) field reached.
                    break
            else:
                return False

        return True

    def validate_fields(self, ast: Dict[str, Any], root_model: Type) -> None:
        """
        Iterates over the requested fields in the AST's serializerOptions and verifies each
        field is allowed according to the registry-based permission settings.
        Raises PermissionDenied if any field is not permitted.
        """
        serializer_options = ast.get("serializerOptions", {})
        requested_fields = serializer_options.get("fields", [])
        for field in requested_fields:
            if not self.is_field_allowed(root_model, field):
                raise PermissionDenied(f"Access to field '{field}' is not permitted.")
