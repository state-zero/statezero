from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union, Tuple, Literal
from collections import deque
import networkx as nx


from statezero.core.config import AppConfig, Registry
from statezero.core.exceptions import PermissionDenied
from statezero.core.interfaces import (
    AbstractDataSerializer,
    AbstractPermission,
    AbstractORMProvider,
)
from statezero.core.types import ActionType, ORMModel, RequestType
from statezero.core.telemetry import get_telemetry_context


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
        self.read_fields_map = self._get_operation_field_map(
            requested_fields=requested_fields, depth=self.depth, operation_type="read"
        )

        # Create/update operations should use depth 0 for performance
        self.create_fields_map = self._get_operation_field_map(
            requested_fields=requested_fields,
            depth=0,  # Nested writes are not supported
            operation_type="create",
        )

        self.update_fields_map = self._get_operation_field_map(
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

    def _process_nested_field_strings(
        self, orm_provider: AbstractORMProvider, field_strings, available_fields_map
    ):
        """
        Build a fields map from a list of dotted field strings like ['fk__m2m', 'field', 'fk__m2m__field'],
        respecting the available fields for each model.

        Args:
            orm_provider: The ORM provider to use for model traversal
            field_strings: List of field strings in the format 'relation__field' or 'field'
            available_fields_map: Dict mapping model names to sets of available fields

        Returns:
            Dict[str, Set[str]]: Dictionary mapping model names to sets of field names
        """
        fields_map = {}
        model_graph: nx.DiGraph = orm_provider.build_model_graph(self.model)

        # Start with the root model
        root_model_name = orm_provider.get_model_name(self.model)
        fields_map[root_model_name] = set()

        for field_string in field_strings:
            parts = field_string.split("__")
            current_model = self.model
            current_model_name = root_model_name

            # Process each part of the field string
            for i, part in enumerate(parts):
                # Check if this field is available for this model
                if (
                    current_model_name in available_fields_map
                    and part in available_fields_map[current_model_name]
                ):
                    # Add the current field to the current model's field set
                    fields_map.setdefault(current_model_name, set()).add(part)

                # If this is the last part, we might need to include all fields if it's a relation
                if i == len(parts) - 1:
                    # Find the field node in the graph to check if it's a relation
                    field_nodes = [
                        node
                        for node in model_graph.successors(current_model_name)
                        if model_graph.nodes[node].get("data")
                        and model_graph.nodes[node].get("data").field_name == part
                    ]

                    if field_nodes:
                        field_node = field_nodes[0]
                        field_data = model_graph.nodes[field_node].get("data")

                        # If this is a relation field, include all available fields of the related model
                        if (
                            field_data
                            and field_data.is_relation
                            and field_data.related_model
                        ):
                            related_model_name = field_data.related_model

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
                    # The relation field is not available, stop traversing
                    break

                # Find the field node in the graph
                field_nodes = [
                    node
                    for node in model_graph.successors(current_model_name)
                    if model_graph.nodes[node].get("data")
                    and model_graph.nodes[node].get("data").field_name == part
                ]

                if not field_nodes:
                    # Field not found, skip to next field string
                    break

                field_node = field_nodes[0]
                field_data = model_graph.nodes[field_node].get("data")

                # If this is a relation field, move to the related model
                if field_data and field_data.is_relation and field_data.related_model:
                    related_model = orm_provider.get_model_by_name(
                        field_data.related_model
                    )
                    current_model = related_model
                    current_model_name = field_data.related_model
                else:
                    # Not a relation field, stop traversing
                    break

        return fields_map

    def _get_operation_field_map(
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
        fields_map = self._get_depth_based_fields(
            orm_provider=self.engine, depth=depth, operation_type=operation_type
        )

        if requested_fields:
            fields_map = self._process_nested_field_strings(
                orm_provider=self.engine,
                field_strings=requested_fields,
                available_fields_map=fields_map,
            )

        return fields_map

    def _has_operation_permission(self, model, operation_type):
        """
        Check if the current request has permission for the specified operation on the model.

        Args:
            model: Model to check permissions for
            operation_type: The type of operation ('read', 'create', 'update', 'delete')

        Returns:
            Boolean indicating if permission is granted for the operation
        """
        try:
            model_config = self.registry.get_config(model)
            allowed_actions = set()

            # Collect all allowed actions from all permissions
            for permission_cls in model_config.permissions:
                permission: AbstractPermission = permission_cls()
                allowed_actions.update(permission.allowed_actions(self.request, model))

            # Map operation types to ActionType enum values
            operation_to_action = {
                "read": ActionType.READ,
                "create": ActionType.CREATE,
                "update": ActionType.UPDATE,
                "delete": ActionType.DELETE,
            }

            # Check if the required action is in the set of allowed actions
            required_action = operation_to_action.get(operation_type, ActionType.READ)
            return required_action in allowed_actions
        except (ValueError, KeyError):
            # Model not registered or permissions not set up
            return False  # Default to denying access for security

    def _get_depth_based_fields(
        self, orm_provider: AbstractORMProvider, depth=0, operation_type="read"
    ):
        """
        Build a fields map by traversing the model graph up to the specified depth.
        Uses operation-specific field permissions.

        Args:
            depth: Maximum depth to traverse in relationship graph
            operation_type: Operation type for field permissions ('read', 'create', 'update')

        Returns:
            Dict[str, Set[str]]: Dictionary mapping model names to sets of field names
        """
        fields_map = {}
        visited = set()
        model_graph: nx.DiGraph = orm_provider.build_model_graph(self.model)

        # Start BFS from the root model
        queue = deque([(self.model, 0)])

        while queue:
            current_model, current_depth = queue.popleft()
            model_name = orm_provider.get_model_name(current_model)

            # Skip if we've already visited this model at this depth or lower
            if (model_name, current_depth) in visited:
                continue
            visited.add((model_name, current_depth))

            # Check if we have permission to read this model
            if not self._has_operation_permission(
                current_model, operation_type=operation_type
            ):
                continue

            # Get fields allowed for this operation type
            allowed_fields = self._get_operation_fields(current_model, operation_type)

            # Initialize fields set for this model
            fields_map.setdefault(model_name, set())

            # Collect all directly accessible fields from the model
            for node in model_graph.successors(model_name):
                # Each successor of the model node is a field node
                field_data = model_graph.nodes[node].get("data")
                if field_data:
                    field_name = field_data.field_name
                    # Add this field to the fields map if it's in allowed_fields
                    if field_name in allowed_fields:
                        fields_map[model_name].add(field_name)

            # Stop traversing if we've reached max depth
            if current_depth >= depth:
                continue

            # Now, traverse relation fields to add related models
            for node in model_graph.successors(model_name):
                field_data = model_graph.nodes[node].get("data")
                if field_data and field_data.is_relation and field_data.related_model:
                    field_name = field_data.field_name
                    # Only traverse relations we have permission to access
                    if field_name in allowed_fields:
                        # Get the related model and add it to the queue
                        related_model = orm_provider.get_model_by_name(
                            field_data.related_model
                        )
                        queue.append((related_model, current_depth + 1))

        return fields_map

    def _get_operation_fields(
        self, model: ORMModel, operation_type: Literal["read", "create", "update"]
    ):
        """
        Get the appropriate field set for a specific operation.

        Args:
            model: Model to get fields for
            operation_type: The operation type ('read', 'create', 'update')

        Returns:
            Set of field names allowed for the operation
        """
        try:
            model_config = self.registry.get_config(model)
            all_fields = self.engine.get_fields(model)

            # Initialize with no fields allowed
            allowed_fields = set()

            # Map operation type to required action
            operation_to_action = {
                "read": ActionType.READ,
                "create": ActionType.CREATE,
                "update": ActionType.UPDATE,
            }
            required_action = operation_to_action.get(operation_type)

            for permission_cls in model_config.permissions:
                permission: AbstractPermission = permission_cls()

                # Only include fields if this permission allows the required action
                if required_action and required_action not in permission.allowed_actions(self.request, model):
                    continue

                # Get the appropriate field set based on operation
                if operation_type == "read":
                    fields: Union[Set[str], Literal["__all__"]] = (
                        permission.visible_fields(self.request, model)
                    )
                elif operation_type == "create":
                    fields: Union[Set[str], Literal["__all__"]] = (
                        permission.create_fields(self.request, model)
                    )
                elif operation_type == "update":
                    fields: Union[Set[str], Literal["__all__"]] = (
                        permission.editable_fields(self.request, model)
                    )
                else:
                    fields = set()  # Default to no fields for unknown operations

                # Record this permission class's field contribution in telemetry
                telemetry_ctx = get_telemetry_context()
                if telemetry_ctx:
                    permission_class_name = f"{permission_cls.__module__}.{permission_cls.__name__}"
                    model_name = self.engine.get_model_name(model)
                    if fields == "__all__":
                        telemetry_ctx.record_permission_class_fields(
                            permission_class_name, model_name, operation_type, list(all_fields)
                        )
                    else:
                        telemetry_ctx.record_permission_class_fields(
                            permission_class_name, model_name, operation_type, list(fields & all_fields)
                        )

                # If any permission allows all fields
                if fields == "__all__":
                    return all_fields

                # Add allowed fields from this permission
                else:  # Ensure we're not operating on the string "__all__"
                    fields &= all_fields  # Ensure fields actually exist
                    allowed_fields |= fields

            return allowed_fields

        except (ValueError, KeyError):
            # Model not registered or permissions not set up
            return set()  # Default to allowing no fields for security

    def parse(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """
        Applies common query modifiers (related fetching, filtering,
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
            self.current_queryset = self.engine.select_related(
                self.current_queryset, ast["selectRelated"]
            )
        if "prefetchRelated" in ast and isinstance(ast["prefetchRelated"], list):
            self.current_queryset = self.engine.prefetch_related(
                self.current_queryset, ast["prefetchRelated"]
            )

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
            self.current_queryset = self.engine.order_by(
                self.current_queryset, ast["orderBy"]
            )

    def _apply_field_selection(self, ast: Dict[str, Any]) -> None:
        """ Apply field selection, updating current queryset."""
        if "fields" in ast and isinstance(ast["fields"], list):
            self.current_queryset = self.engine.select_fields(
                self.current_queryset, ast["fields"]
            )

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
        """ Pass model explicitly to create method."""
        data = ast.get("data", {})
        validated_data = self.serializer.deserialize(
            model=self.model,
            data=data,
            partial=False,
            request=self.request,
            fields_map=self.create_fields_map,
        )
        record = self.engine.create(
            self.model,
            validated_data,
            self.serializer,
            self.request,
            self.create_fields_map,
        )
        serialized = self.serializer.serialize(
            record,
            self.model,
            many=False,
            depth=self.depth,
            fields_map=self.read_fields_map,
        )
        return {
            "data": serialized,
            "metadata": {"created": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_bulk_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Handle bulk create operation."""
        data_list = ast.get("data", [])

        # Check model-level CREATE permission
        if not self._has_operation_permission(self.model, operation_type="create"):
            raise PermissionDenied("Create not allowed")

        # Validate all data items using many=True
        validated_data_list = self.serializer.deserialize(
            model=self.model,
            data=data_list,
            partial=False,
            request=self.request,
            fields_map=self.create_fields_map,
            many=True,
        )

        # Bulk create all records
        records = self.engine.bulk_create(
            self.model,
            validated_data_list,
            self.serializer,
            self.request,
            self.create_fields_map,
        )

        # Serialize the created records
        serialized = self.serializer.serialize(
            records,
            self.model,
            many=True,
            depth=self.depth,
            fields_map=self.read_fields_map,
        )
        return {
            "data": serialized,
            "metadata": {"created": True, "response_type": ResponseType.QUERYSET.value},
        }

    def _handle_update(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to update method."""
        data = ast.get("data", {})
        validated_data = self.serializer.deserialize(
            model=self.model,
            data=data,
            partial=True,
            request=self.request,
            fields_map=self.update_fields_map,
        )
        ast["data"] = validated_data

        # Retrieve permissions from the registry
        permissions = self.registry.get_config(self.model).permissions

        # Get the readable fields for this model using our existing method
        readable_fields = self._get_operation_fields(self.model, "read")

        # Update records and get the count and affected instance IDs
        updated_count, updated_instances = self.engine.update(
            self.current_queryset,  # Pass current queryset
            ast,
            self.request,
            permissions,
            readable_fields=readable_fields,  # Pass readable fields to the update method
        )

        data = self.serializer.serialize(
            updated_instances,
            self.model,
            many=True,
            depth=0,  # Always use depth=0 for updates
            fields_map=self.read_fields_map,
        )

        return {
            "data": data,
            "metadata": {
                "updated": True,
                "updated_count": updated_count,
                "response_type": ResponseType.QUERYSET.value,
            },
        }

    def _handle_delete(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to delete method."""
        permissions = self.registry.get_config(self.model).permissions
        deleted_count, rows_deleted = self.engine.delete(
            self.current_queryset, ast, self.request, permissions
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
        """ Pass model explicitly to update_instance method."""
        # Extract and deserialize the data.
        raw_data = ast.get("data", {})
        # Allow partial updates.
        validated_data = self.serializer.deserialize(
            model=self.model,
            data=raw_data,
            partial=True,
            request=self.request,
            fields_map=self.update_fields_map,
        )
        # Replace raw data with validated data in the AST.
        ast["data"] = validated_data

        # Retrieve permissions from the self.registry.
        permissions = self.registry.get_config(self.model).permissions

        # Delegate to the engine's instance-based update method.
        updated_instance = self.engine.update_instance(
            self.model,
            ast,
            self.request,
            permissions,
            self.serializer,
            fields_map=self.update_fields_map,
        )

        # Serialize the updated instance for the response.
        serialized = self.serializer.serialize(
            updated_instance,
            self.model,
            many=False,
            depth=self.depth,
            fields_map=self.read_fields_map,
        )
        return {
            "data": serialized,
            "metadata": {"updated": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_delete_instance(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles deletion of a single instance.
        Typically, no additional data deserialization is needed beyond the filter,
        so we simply verify that a filter is provided and then delegate to the engine.
        """
        filter_ast = ast.get("filter")
        if not filter_ast:
            raise ValueError("Filter is required for delete_instance operation")

        # If needed, you could deserialize the filter here.
        # For example, if your serializer has a method to process filter conditions,
        # you could call it. Otherwise, assume the filter is valid.

        # Retrieve permissions from the self.registry.
        permissions = self.registry.get_config(self.model).permissions

        # Delegate to the engine's instance-based delete method.
        deleted_count = self.engine.delete_instance(
            self.model, ast, self.request, permissions
        )

        return {
            "data": deleted_count,
            "metadata": {"deleted": True, "response_type": ResponseType.BOOLEAN.value},
        }

    def _handle_get(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to get method."""
        # Retrieve permissions from the registry
        permissions = self.registry.get_config(self.model).permissions
        record = self.engine.get(self.current_queryset, ast, self.request, permissions)
        serialized = self.serializer.serialize(
            record,
            self.model,
            many=False,
            depth=self.depth,
            fields_map=self.read_fields_map,
        )
        return {
            "data": serialized,
            "metadata": {"get": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_get_or_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to get_or_create method."""
        # Validate and split lookup/defaults (without extra wrapping)
        validated_lookup, validated_defaults = self._validate_and_split_lookup_defaults(
            ast, partial=True
        )

        # Optionally update the AST if needed:
        ast["lookup"] = validated_lookup
        ast["defaults"] = validated_defaults

        # Retrieve permissions from configuration
        permissions = self.registry.get_config(self.model).permissions

        # Call the ORM layer and pass the serializer and request/permissions
        record, created = self.engine.get_or_create(
            self.current_queryset,  # Pass current queryset
            {"lookup": ast.get("lookup", {}), "defaults": ast.get("defaults", {})},
            serializer=self.serializer,
            req=self.request,
            permissions=permissions,
            create_fields_map=self.create_fields_map,
        )

        serialized = self.serializer.serialize(
            record,
            self.model,
            many=False,
            depth=self.depth,
            fields_map=self.read_fields_map,
        )
        return {
            "data": serialized,
            "metadata": {
                "created": created,
                "response_type": ResponseType.INSTANCE.value,
            },
        }

    def _handle_update_or_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to update_or_create method."""
        # Validate and split lookup/defaults.
        validated_lookup, validated_defaults = self._validate_and_split_lookup_defaults(
            ast, partial=True
        )

        # Optionally update the AST if needed:
        ast["lookup"] = validated_lookup
        ast["defaults"] = validated_defaults

        # Retrieve permissions from configuration.
        permissions = self.registry.get_config(self.model).permissions

        # Call the ORM update_or_create method, passing the serializer, request, and permissions.
        record, created = self.engine.update_or_create(
            self.current_queryset,  # Pass current queryset
            {"lookup": ast.get("lookup", {}), "defaults": ast.get("defaults", {})},
            req=self.request,
            serializer=self.serializer,
            permissions=permissions,
            update_fields_map=self.update_fields_map,
            create_fields_map=self.create_fields_map,
        )

        serialized = self.serializer.serialize(
            record,
            self.model,
            many=False,
            depth=self.depth,
            fields_map=self.read_fields_map,
        )
        return {
            "data": serialized,
            "metadata": {
                "created": created,
                "response_type": ResponseType.INSTANCE.value,
            },
        }

    def _handle_first(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to first method."""
        record = self.engine.first(self.current_queryset)
        serialized = self.serializer.serialize(
            record,
            self.model,
            many=False,
            depth=self.depth,
            fields_map=self.read_fields_map,
        )
        return {
            "data": serialized,
            "metadata": {"first": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_last(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to last method."""
        record = self.engine.last(self.current_queryset)
        serialized = self.serializer.serialize(
            record,
            self.model,
            many=False,
            depth=self.depth,
            fields_map=self.read_fields_map,
        )
        return {
            "data": serialized,
            "metadata": {"last": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_exists(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to exists method."""
        exists_flag = self.engine.exists(self.current_queryset)
        return {
            "data": exists_flag,
            "metadata": {
                "exists": exists_flag,
                "response_type": ResponseType.NUMBER.value,
            },
        }

    def _handle_aggregate(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to all aggregate methods."""
        from statezero.core.query_cache import get_cached_query_result, cache_query_result

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

            result_data = self.engine.aggregate(self.current_queryset, agg_list)
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

            if op_type == "count":
                result_val = self.engine.count(self.current_queryset, field)
                result = {
                    "data": result_val,
                    "metadata": {
                        "count": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }
                cache_query_result(self.current_queryset, result, operation_context)
                return result
            elif op_type == "sum":
                result_val = self.engine.sum(self.current_queryset, field)
                result = {
                    "data": result_val,
                    "metadata": {
                        "sum": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }
                cache_query_result(self.current_queryset, result, operation_context)
                return result
            elif op_type == "avg":
                result_val = self.engine.avg(self.current_queryset, field)
                result = {
                    "data": result_val,
                    "metadata": {
                        "avg": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }
                cache_query_result(self.current_queryset, result, operation_context)
                return result
            elif op_type == "min":
                result_val = self.engine.min(self.current_queryset, field)
                result = {
                    "data": result_val,
                    "metadata": {
                        "min": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }
                cache_query_result(self.current_queryset, result, operation_context)
                return result
            elif op_type == "max":
                result_val = self.engine.max(self.current_queryset, field)
                result = {
                    "data": result_val,
                    "metadata": {
                        "max": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }
                cache_query_result(self.current_queryset, result, operation_context)
                return result

    def _handle_read(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        """ Pass current queryset to fetch_list method."""
        from statezero.core.query_cache import get_cached_query_result, cache_query_result

        offset_raw = self.serializer_options.get("offset", 0)
        limit_raw = self.serializer_options.get("limit", self.config.default_limit)
        offset_val = int(offset_raw) if offset_raw is not None else None
        limit_val = int(limit_raw) if limit_raw is not None else None

        # Retrieve permissions from configuration
        permissions = self.registry.get_config(self.model).permissions

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
        from statezero.core.query_cache import acquire_query_lock
        acquire_query_lock(paginated_qs, operation_context)

        # Execute query with permission checks
        # Pass UNSLICED queryset so permission checks can filter it,
        # but with offset/limit so fetch_list can apply pagination after permission checks
        rows = self.engine.fetch_list(
            self.current_queryset,
            offset=offset,
            limit=limit_val,
            req=self.request,
            permissions=permissions,
        )

        # Serialize
        serialized = self.serializer.serialize(
            rows,
            self.model,
            many=True,
            depth=self.depth,
            fields_map=self.read_fields_map,
        )

        result = {
            "data": serialized,
            "metadata": {"read": True, "response_type": ResponseType.QUERYSET.value},
        }

        # Cache the result with operation context
        cache_query_result(paginated_qs, result, operation_context)

        return result

    # --- Helper Methods ---

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
            "update_or_create": ActionType.UPDATE,
            "delete": ActionType.DELETE,
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
