from enum import Enum
from typing import Any, Callable, Dict, List, Set, Type

import networkx as nx

from statezero.core.config import Registry
from statezero.core.exceptions import PermissionDenied, ValidationError
from statezero.core.interfaces import AbstractPermission
from statezero.core.types import ActionType, ORMModel, RequestType


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
        Aggregates the visible fields from permission instances that allow READ action.
        Only includes fields from permissions that grant READ access.
        """
        allowed_fields: Set[str] = set()
        for perm in self._aggregate_permission_instances(model):
            # Only include fields from permissions that allow READ action
            if ActionType.READ not in perm.allowed_actions(self.request, model):
                continue

            fields = perm.visible_fields(self.request, model)
            if fields == "__all__":
                # If any permission allows all fields, return all available fields
                from statezero.adaptors.django.config import config

                return config.orm_provider.get_fields(model)
            allowed_fields |= fields
        return allowed_fields

    def _has_read_permission(self, model: Type) -> bool:
        """
        Checks if any of the permission instances for the model allow the READ action.
        """
        for perm in self._aggregate_permission_instances(model):
            if ActionType.READ in perm.allowed_actions(self.request, model):
                return True
        return False

    def _is_additional_field(self, model: Type, field_name: str) -> bool:
        """
        Check if a field is an additional (computed) field that doesn't exist in the Django model.
        """
        try:
            config = self.registry.get_config(model)
            additional_field_names = {f.name for f in config.additional_fields}
            return field_name in additional_field_names
        except (ValueError, AttributeError):
            return False

    def _field_exists_in_django_model(self, model: Type, field_path: str) -> bool:
        """
        Check if a field path exists in the actual Django model (not just additional fields).
        This validates that Django ORM can actually filter/query on this field.
        """
        try:
            # Remove any lookup operators (e.g., 'name__icontains' -> 'name')
            SUPPORTED_OPERATORS = {
                "contains",
                "icontains",
                "startswith",
                "istartswith",
                "endswith",
                "iendswith",
                "lt",
                "gt",
                "lte",
                "gte",
                "in",
                "eq",
                "exact",
                "isnull",
            }

            field_parts = field_path.split("__")
            # Find where the lookup operators start
            base_field_parts = []
            for part in field_parts:
                if part in SUPPORTED_OPERATORS:
                    break
                base_field_parts.append(part)

            # Traverse the Django model fields
            current_model = model
            for field_name in base_field_parts:
                try:
                    field = current_model._meta.get_field(field_name)
                    if field.is_relation and hasattr(field, "related_model"):
                        current_model = field.related_model
                except:
                    # Field doesn't exist in Django model
                    return False

            return True
        except:
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
            if part not in allowed and "__all__" not in str(allowed):
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

    def validate_filterable_field(self, model: Type, field_path: str) -> None:
        """
        Validates that a field path can be used for filtering operations.
        Checks both field existence and user permissions.
        Raises ValidationError if the field is an additional field or doesn't exist in Django model.
        Raises PermissionDenied if the user doesn't have permission to access the field.
        """
        base_field = field_path.split("__")[0]

        # Check if it's an additional field (these can't be filtered)
        if self._is_additional_field(model, base_field):
            raise ValidationError(
                f"Cannot filter on computed field '{base_field}'. "
                f"Computed fields are read-only and cannot be used in filters. "
                f"Consider using Django's computed fields, database annotations, or filter on the underlying fields instead."
            )

        # Check if the field actually exists in the Django model
        if not self._field_exists_in_django_model(model, field_path):
            raise ValidationError(
                f"Field '{field_path}' does not exist on model {model.__name__}. "
                f"Please check the field name and ensure it's a valid Django model field."
            )

        # Check if the user has permission to access this field
        if not self.is_field_allowed(model, field_path):
            raise PermissionDenied(
                f"Permission denied: You do not have access to filter on field '{field_path}'"
            )

    def validate_filter_conditions(self, ast_node: Dict[str, Any], model: Type) -> None:
        """
        Recursively validates filter conditions in an AST node to ensure all fields are filterable.
        """
        if not isinstance(ast_node, dict):
            return

        node_type = ast_node.get("type")

        # Handle filter nodes
        if node_type == "filter":
            conditions = ast_node.get("conditions", {})
            for field_path in conditions.keys():
                self.validate_filterable_field(model, field_path)

        # Handle exclude nodes (they also filter, so same validation applies)
        elif node_type == "exclude":
            if "child" in ast_node:
                self.validate_filter_conditions(ast_node["child"], model)
            else:
                # Direct exclude conditions
                conditions = ast_node.get("conditions", {})
                for field_path in conditions.keys():
                    self.validate_filterable_field(model, field_path)

        # Recursively validate children
        if "children" in ast_node:
            for child in ast_node["children"]:
                self.validate_filter_conditions(child, model)

        if "child" in ast_node:
            self.validate_filter_conditions(ast_node["child"], model)

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

    def validate_ast(self, ast: Dict[str, Any], root_model: Type) -> None:
        """
        Complete AST validation including both field permissions and filter validation.
        """
        # Validate field access permissions
        self.validate_fields(ast, root_model)

        # Validate filter conditions to ensure no additional fields are used
        filter_node = ast.get("filter")
        if filter_node:
            self.validate_filter_conditions(filter_node, root_model)

        # Also validate any exclude conditions
        exclude_node = ast.get("exclude")
        if exclude_node:
            self.validate_filter_conditions(exclude_node, root_model)
