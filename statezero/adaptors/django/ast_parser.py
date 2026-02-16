from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union, Tuple, Literal
from collections import deque


from django.db.models import Avg, Count, Max, Min, Sum
from django.db.models.fields.related import ForeignObjectRel

from statezero.core.config import AppConfig, Registry, EXTRA_FIELDS_ERROR
from statezero.core.exceptions import (
    MultipleObjectsReturned,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from statezero.core.interfaces import (
    AbstractDataSerializer,
    AbstractORMProvider,
)
from statezero.core.types import ActionType, ORMModel, RequestType
from statezero.core.telemetry import get_telemetry_context

# Lookup operators and date/time transforms that are not real model fields
_FILTER_MODIFIERS = {
    # Lookup operators
    "contains", "icontains", "startswith", "istartswith",
    "endswith", "iendswith", "lt", "gt", "lte", "gte",
    "in", "eq", "exact", "iexact", "isnull", "range",
    "regex", "iregex",
    # Date/time transforms
    "year", "month", "day", "hour", "minute", "second",
    "week", "week_day", "iso_week_day", "quarter",
    "iso_year", "date", "time",
}


class ResponseType(Enum):
    INSTANCE = "instance"
    QUERYSET = "queryset"
    NUMBER = "number"
    BOOLEAN = "boolean"
    NONE = "none"


class ASTParser:
    """
    Parses an abstract syntax tree (AST) representing an ORM operation.
    Delegates each operation (create, update, delete, etc.) to a dedicated handler
    and hardcodes the response type in the metadata based on the operation.
    """

    def __init__(
        self,
        engine: AbstractORMProvider,
        serializer: AbstractDataSerializer,
        model: Type,
        config: AppConfig,
        registry: Registry,
        base_queryset: Any,  # ADD: Base queryset to manage state
        serializer_options: Optional[Dict[str, Any]] = None,
        request: Optional[RequestType] = None,
    ):
        self.engine = engine
        self.serializer = serializer
        self.model = model
        self.config = config
        self.registry = registry
        self.current_queryset = base_queryset  # ADD: Track current queryset state
        self._model_name = engine.get_model_name(model)
        self.serializer_options = serializer_options or {}
        self.request = request

        # Process field selection if present
        requested_fields = self.serializer_options.get("fields", [])

        # Configure the serializer options
        self.depth = int(self.serializer_options.get("depth", 0))

        # If Process fields are provided, override the user supplied depth
        if requested_fields:
            self.depth = (
                max((field.count("__") for field in requested_fields), default=0) + 1
            )

        # Get the raw field map
        self.read_fields_map = self._build_permitted_fields_map(
            requested_fields=requested_fields, depth=self.depth, operation_type="read"
        )

        # Create/update operations should use depth 0 for performance
        self.create_fields_map = self._build_permitted_fields_map(
            requested_fields=requested_fields,
            depth=0,  # Nested writes are not supported
            operation_type="create",
        )

        self.update_fields_map = self._build_permitted_fields_map(
            requested_fields=requested_fields,
            depth=0,  # Nested writes are not supported
            operation_type="update",
        )

        # Record permission-validated fields in telemetry
        telemetry_ctx = get_telemetry_context()
        if telemetry_ctx:
            model_name = self.engine.get_model_name(self.model)
            # Record read fields
            if self.read_fields_map:
                telemetry_ctx.record_permission_fields(
                    model_name,
                    "read",
                    list(self.read_fields_map.get(model_name, set()))
                )
            # Record create fields
            if self.create_fields_map:
                telemetry_ctx.record_permission_fields(
                    model_name,
                    "create",
                    list(self.create_fields_map.get(model_name, set()))
                )
            # Record update fields
            if self.update_fields_map:
                telemetry_ctx.record_permission_fields(
                    model_name,
                    "update",
                    list(self.update_fields_map.get(model_name, set()))
                )

        # Add field maps to serializer options
        self.serializer_options["read_fields_map"] = self.read_fields_map
        self.serializer_options["create_fields_map"] = self.create_fields_map
        self.serializer_options["update_fields_map"] = self.update_fields_map

        # Lookup table mapping AST op types to handler methods.
        self.handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "create": self._handle_create,
            "bulk_create": self._handle_bulk_create,
            "update": self._handle_update,
            "delete": self._handle_delete,
            "get": self._handle_get,
            "get_or_create": self._handle_get_or_create,
            "update_or_create": self._handle_update_or_create,
            "first": self._handle_first,
            "last": self._handle_last,
            "exists": self._handle_exists,
            "count": self._handle_aggregate,
            "sum": self._handle_aggregate,
            "avg": self._handle_aggregate,
            "min": self._handle_aggregate,
            "max": self._handle_aggregate,
            "aggregate": self._handle_aggregate,
            "update_instance": self._handle_update_instance,
            "delete_instance": self._handle_delete_instance,
        }
        self.default_handler = self._handle_read

    def _serialize(self, data, many=False, depth=None):
        """Serialize data using standard read settings."""
        return self.serializer.serialize(
            data, self.model, many=many,
            depth=depth if depth is not None else self.depth,
            fields_map=self.read_fields_map,
        )

    def _resolve_field_relation(self, model, field_name):
        """Check if field_name is a relation on model. Returns (is_relation, related_model_class)."""
        try:
            field = model._meta.get_field(field_name)
            # For reverse relations (ForeignObjectRel), only include if explicitly in model config fields
            if isinstance(field, ForeignObjectRel):
                try:
                    model_config = self.registry.get_config(model)
                    configured_fields = model_config.fields
                    if configured_fields == "__all__" or field_name not in configured_fields:
                        return False, None
                except (ValueError, KeyError):
                    return False, None
                # Reverse relation explicitly configured — treat as relation
                if getattr(field, 'related_model', None):
                    return True, field.related_model
                return False, None
            if field.is_relation and getattr(field, 'related_model', None):
                return True, field.related_model
            return False, None
        except Exception:
            # Check additional_fields (computed fields that might be relations)
            try:
                for af in self.registry.get_config(model).additional_fields:
                    if af.name == field_name and getattr(af.field, 'related_model', None):
                        return True, af.field.related_model
            except (ValueError, KeyError):
                pass
            return False, None

    def _permitted_fields(self, model, operation_type):
        """Permitted fields for an operation. Empty set = no permission."""
        from statezero.adaptors.django.permission_utils import has_operation_permission, resolve_permission_fields
        try:
            model_config = self.registry.get_config(model)
            if not has_operation_permission(model_config, self.request, operation_type):
                return set()
            result = resolve_permission_fields(model_config, self.request, operation_type,
                                               self.engine.get_fields(model))

            # Record telemetry for each permission class's contribution
            telemetry_ctx = get_telemetry_context()
            if telemetry_ctx:
                model_name = self.engine.get_model_name(model)
                for permission_cls in model_config.permissions:
                    permission_class_name = f"{permission_cls.__module__}.{permission_cls.__name__}"
                    telemetry_ctx.record_permission_class_fields(
                        permission_class_name, model_name, operation_type, list(result)
                    )

            return result
        except (ValueError, KeyError):
            return set()

    def _resolve_explicit_field_paths(
        self, field_strings, available_fields_map,
        operation_type: Literal["read", "create", "update"] = "read",
    ):
        """
        Build a fields map from a list of dotted field strings like ['fk__m2m', 'field', 'fk__m2m__field'],
        respecting the available fields for each model.

        When explicit field paths traverse beyond the depth limit, this resolves
        permissions for the encountered models on-the-fly so that depth only controls
        auto-expansion, not hard-blocks explicit requests.

        Args:
            field_strings: List of field strings in the format 'relation__field' or 'field'
            available_fields_map: Dict mapping model names to sets of available fields
            operation_type: Operation type for resolving permissions on newly encountered models

        Returns:
            Dict[str, Set[str]]: Dictionary mapping model names to sets of field names
        """
        fields_map = {}

        # Start with the root model
        root_model_name = self._model_name
        fields_map[root_model_name] = set()

        for field_string in field_strings:
            parts = field_string.split("__")
            current_model = self.model
            current_model_name = root_model_name

            # Process each part of the field string
            for i, part in enumerate(parts):
                # If this model isn't in the available map yet (beyond depth limit),
                # resolve its permissions now — explicit field paths override depth.
                if current_model_name not in available_fields_map:
                    perm_fields = self._permitted_fields(current_model, operation_type)
                    if perm_fields:
                        available_fields_map[current_model_name] = perm_fields

                # Check if this field is available for this model
                if (
                    current_model_name in available_fields_map
                    and part in available_fields_map[current_model_name]
                ):
                    # Add the current field to the current model's field set
                    fields_map.setdefault(current_model_name, set()).add(part)

                # If this is the last part, we might need to include all fields if it's a relation
                if i == len(parts) - 1:
                    is_relation, related_model_cls = self._resolve_field_relation(current_model, part)

                    # If this is a relation field, include all available fields of the related model
                    if is_relation and related_model_cls:
                        related_model_name = self.engine.get_model_name(related_model_cls)

                        # Resolve permissions for the related model if needed
                        if related_model_name not in available_fields_map:
                            perm_fields = self._permitted_fields(related_model_cls, operation_type)
                            if perm_fields:
                                available_fields_map[related_model_name] = perm_fields

                        # Include all available fields for this related model
                        if related_model_name in available_fields_map:
                            fields_map.setdefault(related_model_name, set()).update(
                                available_fields_map[related_model_name]
                            )
                    break

                # Otherwise, we need to traverse to the related model if allowed
                # First, check if the relation field is available
                if (
                    current_model_name not in available_fields_map
                    or part not in available_fields_map[current_model_name]
                ):
                    if self.config.effective_extra_fields == EXTRA_FIELDS_ERROR:
                        raise ValidationError(
                            f"Field '{part}' is not permitted on model '{current_model_name}'."
                        )
                    # The relation field is not available, stop traversing
                    break

                # Check if this field is a relation using _meta
                is_relation, related_model_cls = self._resolve_field_relation(current_model, part)

                if not is_relation or not related_model_cls:
                    if self.config.effective_extra_fields == EXTRA_FIELDS_ERROR:
                        if not is_relation:
                            raise ValidationError(
                                f"Field '{part}' does not exist on model '{current_model_name}'."
                            )
                    # Not a relation field, stop traversing
                    break

                # Move to the related model
                current_model = related_model_cls
                current_model_name = self.engine.get_model_name(related_model_cls)

        return fields_map

    def _build_permitted_fields_map(
        self,
        requested_fields: Optional[Set[str]] = None,
        depth=0,
        operation_type: Literal["read", "create", "update"] = "read",
    ) -> Dict[str, Set[str]]:
        """
        Build a fields map for a specific operation type.

        Args:
            requested_fields: Optional set of explicitly requested fields
            depth: Maximum depth for related models to include
            operation_type: Operation type ('read', 'create', 'update')

        Returns:
            Dict[str, Set[str]]: Fields map with model names as keys and sets of field names as values
        """
        # Build a fields map specific to this operation type
        fields_map = self._expand_fields_to_depth(
            depth=depth, operation_type=operation_type
        )

        # Merge filter fields into requested_fields so they go through permission validation
        # This must happen AFTER _expand_fields_to_depth resolves __all__ to actual field names
        filter_fields = self.serializer_options.get("_filter_fields", set())
        if filter_fields and requested_fields:
            requested_fields = set(requested_fields) | filter_fields

        if requested_fields:
            fields_map = self._resolve_explicit_field_paths(
                field_strings=requested_fields,
                available_fields_map=fields_map,
                operation_type=operation_type,
            )

        return fields_map

    def _expand_fields_to_depth(
        self, depth=0, operation_type="read"
    ):
        """
        Build a fields map by traversing model relationships up to the specified depth.
        Uses operation-specific field permissions and Django _meta API directly.

        Args:
            depth: Maximum depth to traverse in relationship graph
            operation_type: Operation type for field permissions ('read', 'create', 'update')

        Returns:
            Dict[str, Set[str]]: Dictionary mapping model names to sets of field names
        """
        fields_map = {}
        visited = set()

        # Start BFS from the root model
        queue = deque([(self.model, 0)])

        while queue:
            current_model, current_depth = queue.popleft()
            model_name = self.engine.get_model_name(current_model)

            # Skip if we've already visited this model at this depth or lower
            if (model_name, current_depth) in visited:
                continue
            visited.add((model_name, current_depth))

            # Get permitted fields for this operation type (includes permission check)
            allowed_fields = self._permitted_fields(current_model, operation_type)
            if not allowed_fields:
                continue

            # Initialize fields set for this model
            fields_map.setdefault(model_name, set())

            # Get model config to check configured fields for reverse relation filtering
            try:
                model_config = self.registry.get_config(current_model)
                configured_fields = model_config.fields
            except (ValueError, KeyError):
                configured_fields = "__all__"

            # Iterate over all fields using Django _meta
            for field in current_model._meta.get_fields():
                field_name = field.name

                # Skip reverse relations unless explicitly configured
                if isinstance(field, ForeignObjectRel):
                    if configured_fields == "__all__" or field_name not in configured_fields:
                        continue

                # Add this field if it's in allowed_fields
                if field_name in allowed_fields:
                    fields_map[model_name].add(field_name)

            # Also check additional_fields (computed fields)
            try:
                for af in self.registry.get_config(current_model).additional_fields:
                    if af.name in allowed_fields:
                        fields_map[model_name].add(af.name)
            except (ValueError, KeyError):
                pass

            # Stop traversing if we've reached max depth
            if current_depth >= depth:
                continue

            # Traverse relation fields to add related models
            for field in current_model._meta.get_fields():
                field_name = field.name

                # Skip reverse relations unless explicitly configured
                if isinstance(field, ForeignObjectRel):
                    if configured_fields == "__all__" or field_name not in configured_fields:
                        continue
                    # Reverse relation explicitly configured
                    if field_name in allowed_fields and getattr(field, 'related_model', None):
                        queue.append((field.related_model, current_depth + 1))
                    continue

                if field.is_relation and getattr(field, 'related_model', None):
                    if field_name in allowed_fields:
                        queue.append((field.related_model, current_depth + 1))

        return fields_map

    # --- Validation Methods (merged from ASTValidator) ---

    def _is_additional_field(self, model: Type, field_name: str) -> bool:
        """Check if a field is an additional (computed) field."""
        try:
            model_config = self.registry.get_config(model)
            additional_field_names = {f.name for f in model_config.additional_fields}
            return field_name in additional_field_names
        except (ValueError, AttributeError):
            return False

    def _field_exists_in_django_model(self, model: Type, field_path: str) -> bool:
        """Check if a field path exists in the actual Django model."""
        try:
            field_parts = field_path.split("__")
            base_field_parts = []
            for part in field_parts:
                if part in _FILTER_MODIFIERS:
                    break
                base_field_parts.append(part)

            current_model = model
            for field_name in base_field_parts:
                if field_name == "pk":
                    return True
                try:
                    field = current_model._meta.get_field(field_name)
                    if self.engine.is_nested_path_field(current_model, field_name):
                        return True
                    if field.is_relation and hasattr(field, "related_model"):
                        current_model = field.related_model
                except Exception:
                    return False
            return True
        except Exception:
            return False

    def is_field_allowed(self, model: Type, field_path: str) -> bool:
        """
        Validates a nested field path by checking permission settings for each model
        encountered along the path.
        """
        parts = field_path.split("__")
        current_model = model

        allowed = self._permitted_fields(current_model, "read")
        if not allowed:
            return False

        for part in parts:
            if part in _FILTER_MODIFIERS:
                break

            if part == "pk" or part == current_model._meta.pk.name:
                break

            if part not in allowed and "__all__" not in str(allowed):
                return False

            if self.engine.is_nested_path_field(current_model, part):
                return True

            # Use _meta to check if this is a relation field
            is_relation, related_model_cls = self._resolve_field_relation(current_model, part)
            if is_relation and related_model_cls:
                allowed = self._permitted_fields(related_model_cls, "read")
                if not allowed:
                    return False
                current_model = related_model_cls
                continue
            else:
                # Check if the field exists at all (non-relation field)
                try:
                    current_model._meta.get_field(part)
                    # It's a non-relation field, stop traversing
                    break
                except Exception:
                    # Check if it's an additional field
                    if self._is_additional_field(current_model, part):
                        break
                    return False

        return True

    def validate_filterable_field(self, model: Type, field_path: str) -> None:
        """
        Validates that a field path can be used for filtering.
        Checks both field existence and user permissions.
        """
        base_field = field_path.split("__")[0]

        if base_field == "pk" or base_field == model._meta.pk.name:
            return

        if self._is_additional_field(model, base_field):
            raise ValidationError(
                f"Cannot filter on computed field '{base_field}'. "
                f"Computed fields are read-only and cannot be used in filters. "
                f"Consider using Django's computed fields, database annotations, or filter on the underlying fields instead."
            )

        if not self._field_exists_in_django_model(model, field_path):
            raise ValidationError(
                f"Field '{field_path}' does not exist on model {model.__name__}. "
                f"Please check the field name and ensure it's a valid Django model field."
            )

        if not self.is_field_allowed(model, field_path):
            raise PermissionDenied(
                f"Permission denied: You do not have access to filter on field '{field_path}'"
            )

    def validate_filter_conditions(self, ast_node: Dict[str, Any], model: Type) -> None:
        """Recursively validates filter conditions in an AST node."""
        if not isinstance(ast_node, dict):
            return

        node_type = ast_node.get("type")

        if node_type == "filter":
            conditions = ast_node.get("conditions", {})
            for field_path in conditions.keys():
                self.validate_filterable_field(model, field_path)
        elif node_type == "exclude":
            if "child" in ast_node:
                self.validate_filter_conditions(ast_node["child"], model)
            else:
                conditions = ast_node.get("conditions", {})
                for field_path in conditions.keys():
                    self.validate_filterable_field(model, field_path)

        if "children" in ast_node:
            for child in ast_node["children"]:
                self.validate_filter_conditions(child, model)

        if "child" in ast_node:
            self.validate_filter_conditions(ast_node["child"], model)

    def validate_fields(self, ast: Dict[str, Any], root_model: Type, error_on_extra: bool = False) -> None:
        """Validates requested fields against permission settings."""
        serializer_options = ast.get("serializerOptions", {})
        requested_fields = serializer_options.get("fields", [])
        for field in requested_fields:
            if error_on_extra:
                if not self._field_exists_in_django_model(root_model, field):
                    raise ValidationError(
                        f"Field '{field}' does not exist on model {root_model.__name__}."
                    )
            if not self.is_field_allowed(root_model, field):
                raise PermissionDenied(f"Access to field '{field}' is not permitted.")

    def validate_ordering_fields(self, ast: Dict[str, Any], model: Type) -> None:
        """Validates that all ordering fields exist on the model."""
        order_by = ast.get("orderBy", [])
        for field_path in order_by:
            clean_path = field_path.lstrip("-")
            if not self._field_exists_in_django_model(model, clean_path):
                raise ValidationError(
                    f"Cannot order by '{field_path}': field does not exist on model {model.__name__}."
                )

    def validate_ast(self, ast: Dict[str, Any], root_model: Type, error_on_extra: bool = False) -> None:
        """Complete AST validation including field permissions, filter, and exclude validation."""
        self.validate_fields(ast, root_model, error_on_extra=error_on_extra)

        filter_node = ast.get("filter")
        if filter_node:
            self.validate_filter_conditions(filter_node, root_model)

        exclude_node = ast.get("exclude")
        if exclude_node:
            self.validate_filter_conditions(exclude_node, root_model)

    def parse(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates the AST, applies common query modifiers (related fetching, filtering,
        ordering, field selection) then delegates the operation to a handler.
        """
        self._apply_related(ast)
        self._apply_filter(ast)
        self._apply_search(ast)
        self._apply_exclude(ast)
        self._apply_ordering(ast)
        self._apply_field_selection(ast)

        op_type = ast.get("type", "read")
        handler = self.handlers.get(op_type, self.default_handler)
        return handler(ast)

    def _apply_related(self, ast: Dict[str, Any]) -> None:
        """ Apply select_related and prefetch_related, updating current queryset."""
        if "selectRelated" in ast and isinstance(ast["selectRelated"], list):
            self.current_queryset = self.current_queryset.select_related(*ast["selectRelated"])
        if "prefetchRelated" in ast and isinstance(ast["prefetchRelated"], list):
            self.current_queryset = self.current_queryset.prefetch_related(*ast["prefetchRelated"])

    def _apply_filter(self, ast: Dict[str, Any]) -> None:
        """ Apply filter from AST to the queryset, updating current queryset."""
        if "filter" in ast and ast["filter"]:
            self.current_queryset = self.engine.filter_node(
                self.current_queryset, ast["filter"]
            )

    def _apply_exclude(self, ast: Dict[str, Any]) -> None:
        """ Apply exclude from AST to the queryset, updating current queryset."""
        if "exclude" in ast and ast["exclude"]:
            self.current_queryset = self.engine.exclude_node(
                self.current_queryset, ast["exclude"]
            )

    def _apply_ordering(self, ast: Dict[str, Any]) -> None:
        """ Apply ordering, updating current queryset."""
        if "orderBy" in ast:
            self.current_queryset = self.current_queryset.order_by(*ast["orderBy"])

    def _apply_field_selection(self, ast: Dict[str, Any]) -> None:
        """ Apply field selection, updating current queryset."""
        if "fields" in ast and isinstance(ast["fields"], list):
            self.current_queryset = self.current_queryset.values(*ast["fields"])

    def _apply_search(self, ast: Dict[str, Any]) -> None:
        """
        If search properties are present at the top level of the AST,
        apply the search using the adapter's search_node() method.

        Expects the AST to have a top-level "search" key containing:
        - searchQuery: the search term
        - searchFields: an array of field names (which may be empty)

        Uses the model's configuration (from the registry) for searchable fields,
        and if the frontend provides searchFields (even an empty list), uses that value.
        """
        search_data = ast.get("search")
        if not search_data:
            return

        search_query = search_data.get("searchQuery")
        if not search_query:
            return

        # Load the model configuration from the registry.
        model_config = self.registry.get_config(self.model)
        config_search_fields = set(getattr(model_config, "searchable_fields", []))
        if not config_search_fields:
            return

        # Use frontend-provided searchFields if available.
        frontend_fields = search_data.get("searchFields")
        if frontend_fields is not None:
            final_search_fields = config_search_fields.intersection(
                set(frontend_fields)
            )
        else:
            final_search_fields = config_search_fields

        # Delegate to the ORM adapter's search_node() method with queryset.
        self.current_queryset = self.engine.search_node(
            self.current_queryset, search_query, final_search_fields
        )

    # --- Operation Handlers with Hard-Coded Response Types ---

    def _handle_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new model instance."""
        self.current_queryset._check_action(ActionType.CREATE)
        data = ast.get("data", {})
        validated_data = self.serializer.deserialize(
            model=self.model,
            data=data,
            partial=False,
            request=self.request,
            fields_map=self.create_fields_map,
        )
        record = self.current_queryset.create(**validated_data)
        return {
            "data": self._serialize(record),
            "metadata": {"created": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_bulk_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """Create multiple model instances using Django's bulk_create."""
        self.current_queryset._check_action(ActionType.BULK_CREATE)
        from statezero.adaptors.django.config import config as django_config

        data_list = ast.get("data", [])

        # Validate all data items using many=True
        validated_data_list = self.serializer.deserialize(
            model=self.model,
            data=data_list,
            partial=False,
            request=self.request,
            fields_map=self.create_fields_map,
            many=True,
        )

        # Bulk create all records via the permissioned queryset
        instances = [self.model(**data) for data in validated_data_list]
        records = self.current_queryset.bulk_create(instances)
        django_config.event_bus.emit_bulk_event(ActionType.BULK_CREATE, records)

        return {
            "data": self._serialize(records, many=True),
            "metadata": {"created": True, "response_type": ResponseType.QUERYSET.value},
        }

    def _handle_update(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to update method."""
        self.current_queryset._check_action(ActionType.UPDATE)
        data = ast.get("data", {})
        validated_data = self.serializer.deserialize(
            model=self.model,
            data=data,
            partial=True,
            request=self.request,
            fields_map=self.update_fields_map,
        )
        ast["data"] = validated_data

        # Update records and get the count and affected instance IDs
        updated_count, updated_instances = self.engine.update(
            self.current_queryset,
            ast,
            self.request,
        )

        return {
            "data": self._serialize(updated_instances, many=True, depth=0),
            "metadata": {
                "updated": True,
                "updated_count": updated_count,
                "response_type": ResponseType.QUERYSET.value,
            },
        }

    def _handle_delete(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to delete method."""
        self.current_queryset._check_action(ActionType.DELETE)
        deleted_count, rows_deleted = self.engine.delete(
            self.current_queryset, ast, self.request
        )
        return {
            "data": None,
            "metadata": {
                "deleted": True,
                "deleted_count": deleted_count,
                "rows_deleted": rows_deleted,
                "response_type": ResponseType.NUMBER.value,
            },
        }

    def _handle_update_instance(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """Update a single model instance."""
        from statezero.adaptors.django.orm import QueryASTVisitor

        raw_data = ast.get("data", {})
        validated_data = self.serializer.deserialize(
            model=self.model,
            data=raw_data,
            partial=True,
            request=self.request,
            fields_map=self.update_fields_map,
        )

        filter_ast = ast.get("filter")
        if not filter_ast:
            raise ValueError("Filter is required for update_instance operation")

        visitor = QueryASTVisitor(self.model)
        q_obj = visitor.visit(filter_ast)
        instance = self.current_queryset.filter(q_obj).get()

        updated_instance = self.serializer.save(
            model=self.model,
            data=validated_data,
            instance=instance,
            partial=True,
            request=self.request,
            fields_map=self.update_fields_map,
        )

        return {
            "data": self._serialize(updated_instance),
            "metadata": {"updated": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_delete_instance(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a single model instance."""
        from statezero.adaptors.django.orm import QueryASTVisitor

        filter_ast = ast.get("filter")
        if not filter_ast:
            raise ValueError("Filter is required for delete_instance operation")

        visitor = QueryASTVisitor(self.model)
        q_obj = visitor.visit(filter_ast)
        instance = self.current_queryset.filter(q_obj).get()

        instance.delete()

        return {
            "data": 1,
            "metadata": {"deleted": True, "response_type": ResponseType.BOOLEAN.value},
        }

    def _handle_get(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """Retrieve a single model instance."""
        from statezero.adaptors.django.orm import QueryASTVisitor

        filter_ast = ast.get("filter")
        if filter_ast:
            visitor = QueryASTVisitor(self.model)
            q_obj = visitor.visit(filter_ast)
            try:
                record = self.current_queryset.filter(q_obj).get()
            except self.model.DoesNotExist:
                raise NotFound(f"No {self.model.__name__} matches the given query.")
            except self.model.MultipleObjectsReturned:
                raise MultipleObjectsReturned(
                    f"Multiple {self.model.__name__} instances match the given query."
                )
        else:
            try:
                record = self.current_queryset.get()
            except self.model.DoesNotExist:
                raise NotFound(f"No {self.model.__name__} matches the given query.")
            except self.model.MultipleObjectsReturned:
                raise MultipleObjectsReturned(
                    f"Multiple {self.model.__name__} instances match the given query."
                )

        return {
            "data": self._serialize(record),
            "metadata": {"get": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_queryset_single(self, ast: Dict[str, Any], method: str) -> Dict[str, Any]:
        """Return a single record from the queryset using the given method (first/last)."""
        record = getattr(self.current_queryset, method)()
        return {
            "data": self._serialize(record),
            "metadata": {method: True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_first(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        return self._handle_queryset_single(ast, "first")

    def _handle_last(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        return self._handle_queryset_single(ast, "last")

    def _lookup_or_mutate(self, ast: Dict[str, Any], existing_action: ActionType, save_on_existing: bool) -> Dict[str, Any]:
        """Shared logic for get_or_create and update_or_create."""
        validated_lookup, validated_defaults = self._validate_and_split_lookup_defaults(
            ast, partial=True
        )
        ast["lookup"] = validated_lookup
        ast["defaults"] = validated_defaults

        lookup = ast.get("lookup", {})
        defaults = ast.get("defaults", {})

        # Normalize foreign keys: replace model instances with their PKs
        merged_data = {
            k: (v.pk if hasattr(v, "_meta") else v)
            for k, v in {**lookup, **defaults}.items()
        }

        # Determine if instance exists
        try:
            instance = self.current_queryset.get(**lookup)
            created = False
        except self.model.DoesNotExist:
            instance = None
            created = True
        except self.model.MultipleObjectsReturned:
            raise MultipleObjectsReturned(
                f"Multiple {self.model.__name__} instances match the given lookup parameters"
            )

        if created or save_on_existing:
            fields_map_to_use = self.create_fields_map if created else self.update_fields_map
            record = self.serializer.save(
                model=self.model,
                data=merged_data,
                instance=instance,
                request=self.request,
                fields_map=fields_map_to_use,
            )
        else:
            record = instance

        return {
            "data": self._serialize(record),
            "metadata": {
                "created": created,
                "response_type": ResponseType.INSTANCE.value,
            },
        }

    def _handle_get_or_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """Get an existing object, or create it if it doesn't exist."""
        return self._lookup_or_mutate(ast, existing_action=ActionType.READ, save_on_existing=False)

    def _handle_update_or_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing object, or create it if it doesn't exist."""
        return self._lookup_or_mutate(ast, existing_action=ActionType.UPDATE, save_on_existing=True)

    def _handle_exists(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Check if the queryset has any results."""
        exists_flag = self.current_queryset.exists()
        return {
            "data": exists_flag,
            "metadata": {
                "exists": exists_flag,
                "response_type": ResponseType.NUMBER.value,
            },
        }

    def _handle_aggregate(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to all aggregate methods."""
        from statezero.adaptors.django.query_cache import get_cached_query_result, cache_query_result

        op_type = ast.get("type")

        # For aggregate operations, we need to include the operation type and field
        # in the cache key because different aggregates on the same queryset
        # produce different results
        if op_type == "aggregate":
            aggs = ast.get("aggregates", {})
            agg_list = []
            for func, field in aggs.items():
                agg_list.append(
                    {"function": func, "field": field, "alias": f"{field}_{func}"}
                )

            # Create operation context from all aggregates
            operation_context = f"aggregate:{','.join(f'{f}:{fld}' for f, fld in aggs.items())}"

            # Try cache with operation context
            cached_result = get_cached_query_result(self.current_queryset, operation_context)
            if cached_result is not None:
                return cached_result

            result_data = self._do_aggregate(self.current_queryset, agg_list)
            result = {
                "data": result_data,
                "metadata": {
                    "aggregate": True,
                    "response_type": ResponseType.NUMBER.value,
                },
            }
            cache_query_result(self.current_queryset, result, operation_context)
            return result
        else:
            field = ast.get("field")
            if not field:
                raise ValueError("Field must be provided for aggregate operations.")

            # Create operation context: "operation_type:field"
            operation_context = f"{op_type}:{field}"

            # Try cache with operation context
            cached_result = get_cached_query_result(self.current_queryset, operation_context)
            if cached_result is not None:
                return cached_result

            agg_func_map = {
                "count": Count,
                "sum": Sum,
                "avg": Avg,
                "min": Min,
                "max": Max,
            }
            agg_func = agg_func_map.get(op_type)
            if not agg_func:
                raise ValueError(f"Unknown aggregate operation: {op_type}")

            raw = self.current_queryset.aggregate(result=agg_func(field))["result"]
            if op_type == "count":
                result_val = int(raw) if raw is not None else 0
            elif op_type == "avg":
                result_val = float(raw) if raw is not None else None
            else:
                result_val = raw

            result = {
                "data": result_val,
                "metadata": {
                    op_type: True,
                    "response_type": ResponseType.NUMBER.value,
                },
            }
            cache_query_result(self.current_queryset, result, operation_context)
            return result

    def _handle_read(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to fetch_list method."""
        from statezero.adaptors.django.query_cache import get_cached_query_result, cache_query_result

        offset_raw = self.serializer_options.get("offset", 0)
        limit_raw = self.serializer_options.get("limit", self.config.default_limit)
        offset_val = int(offset_raw) if offset_raw is not None else None
        limit_val = int(limit_raw) if limit_raw is not None else None

        # Apply LIMIT/OFFSET to queryset BEFORE checking cache
        # This ensures the cache key includes pagination in the SQL
        offset = offset_val or 0
        if limit_val is None:
            paginated_qs = self.current_queryset[offset:]
        else:
            paginated_qs = self.current_queryset[offset : offset + limit_val]

        # Create operation context that includes fields
        # since serialization happens after SQL execution
        # Note: depth is implicit in fields_map (which includes nested model fields)
        fields_str = str(sorted(str(self.read_fields_map))) if self.read_fields_map else "default"
        operation_context = f"read:fields={fields_str}"

        # Try cache with the paginated queryset and operation context
        # This also handles waiting for other requests processing the same query (request coalescing)
        cached_result = get_cached_query_result(paginated_qs, operation_context)
        if cached_result is not None:
            return cached_result

        # Cache miss - try to acquire lock for request coalescing
        # If we can't acquire lock, another request is processing this query
        # and get_cached_query_result already waited for it. If we're still here,
        # either we got the lock or the wait timed out, so execute the query.
        from statezero.adaptors.django.query_cache import acquire_query_lock
        acquire_query_lock(paginated_qs, operation_context)

        if limit_val is None:
            rows = self.current_queryset[offset:]
        else:
            rows = self.current_queryset[offset : offset + limit_val]

        result = {
            "data": self._serialize(rows, many=True),
            "metadata": {"read": True, "response_type": ResponseType.QUERYSET.value},
        }

        # Cache the result with operation context
        cache_query_result(paginated_qs, result, operation_context)

        return result

    # --- Helper Methods ---

    @staticmethod
    def _do_aggregate(queryset, agg_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Perform aggregation operations directly on the queryset."""
        agg_func_map = {"count": Count, "sum": Sum, "avg": Avg, "min": Min, "max": Max}
        agg_expressions = {}
        for agg in agg_list:
            func_cls = agg_func_map.get(agg["function"])
            if not func_cls:
                from statezero.core.exceptions import ValidationError
                raise ValidationError(f"Unknown aggregate function: {agg['function']}")
            agg_expressions[agg["alias"]] = func_cls(agg["field"])
        raw = queryset.aggregate(**agg_expressions)
        return {"data": raw, "metadata": {"aggregated": True}}

    def _validate_and_split_lookup_defaults(
        self, ast: Dict[str, Any], partial: bool = False
    ) -> Tuple[Dict[str, str]]:
        """
        Validates the lookups and the defaults separately, using appropriate field maps for each.
        Lookup uses read_fields_map, defaults uses create_fields_map.
        """
        raw_lookup = ast.get("lookup", {})
        raw_defaults = ast.get("defaults", {})

        # Validate lookup with read_fields_map (for filtering)
        validated_lookup = self.serializer.deserialize(
            model=self.model,
            data=raw_lookup,
            partial=partial,
            request=self.request,
            fields_map=self.read_fields_map,
        )

        # Validate defaults with create_fields_map (for creation)
        validated_defaults = self.serializer.deserialize(
            model=self.model,
            data=raw_defaults,
            partial=partial,
            request=self.request,
            fields_map=self.create_fields_map,
        )

        return validated_lookup, validated_defaults

    # --- Static Methods for Operation Extraction ---

    @staticmethod
    def _extract_all_operations(ast_node: Dict[str, Any]) -> Set[str]:
        ops: Set[str] = set()
        if "type" in ast_node:
            ops.add(ast_node["type"])
        for value in ast_node.values():
            if isinstance(value, dict):
                ops |= ASTParser._extract_all_operations(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        ops |= ASTParser._extract_all_operations(item)
        return ops

    @staticmethod
    def get_requested_action_types(ast: Dict[str, Any]) -> Set[ActionType]:
        all_ops = ASTParser._extract_all_operations(ast)
        OPERATION_MAPPING = {
            "create": ActionType.CREATE,
            "bulk_create": ActionType.BULK_CREATE,
            "update": ActionType.UPDATE,
            "update_instance": ActionType.UPDATE,
            "update_or_create": ActionType.UPDATE,
            "delete": ActionType.DELETE,
            "delete_instance": ActionType.DELETE,
            "get": ActionType.READ,
            "get_or_create": ActionType.READ,
            "first": ActionType.READ,
            "last": ActionType.READ,
            "read": ActionType.READ,
            "exists": ActionType.READ,
            "count": ActionType.READ,
            "sum": ActionType.READ,
            "avg": ActionType.READ,
            "min": ActionType.READ,
            "max": ActionType.READ,
            "aggregate": ActionType.READ,
        }
        return {OPERATION_MAPPING.get(op, ActionType.READ) for op in all_ops}
