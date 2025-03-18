from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union

from ormbridge.core.config import AppConfig, Registry
from ormbridge.core.interfaces import AbstractDataSerializer
from ormbridge.core.types import ActionType, ORMModel, RequestType

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
        engine: Any,
        serializer: AbstractDataSerializer,
        model: Type,
        config: AppConfig,
        registry: Registry,
        serializer_options: Optional[Dict[str, Any]] = None,
        request: Optional[RequestType] = None,
    ):
        self.engine = engine
        self.serializer = serializer
        self.model = model
        self.config = config
        self.registry = registry
        self.serializer_options = serializer_options or {}

        # Process field selection if present
        requested_fields = self.serializer_options.get("fields", [])

        # Only process fields when explicitly provided and non-empty
        if requested_fields:
            # Process fields into a proper fields_map with support for nested fields
            fields_map = self._process_requested_fields(requested_fields)
            self.serializer_options["fields_map"] = fields_map

        self.ser_args = {
            "depth": int(self.serializer_options.get("depth", 0)),
            "fields_map": self.serializer_options.get("fields_map", {}),
        }
        # Lookup table mapping AST op types to handler methods.
        self.handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "create": self._handle_create,
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
        self.request = request

    def _process_requested_fields(self, requested_fields):
        """
        Process the requested fields, including nested fields, and build a complete fields_map.
        """
        # Initialize fields_map
        fields_map = {}

        # Get the model name
        model_name = self.config.orm_provider.get_model_name(self.model)
        fields_map[model_name] = set()

        # Build model graph (or use cached version if available)
        model_graph = self.config.orm_provider.build_model_graph(self.model)

        # Process each requested field
        for field in requested_fields:
            if "__" in field:
                # This is a nested field
                parts = field.split("__")
                current_model = self.model
                current_model_name = model_name

                # Navigate through each part of the nested field
                for i, part in enumerate(parts):
                    # Add this field to the current model's allowed fields
                    fields_map.setdefault(current_model_name, set()).add(part)

                    # If this isn't the last part, we need to follow the relationship
                    if i < len(parts) - 1:
                        # Get the field node
                        field_node = f"{current_model_name}::{part}"

                        # Check if this is a relation field
                        if field_node in model_graph.nodes:
                            field_data = model_graph.nodes[field_node]["data"]
                            if field_data.is_relation:
                                # Move to the related model for the next part
                                current_model_name = field_data.related_model
                                # Get the actual model class
                                current_model = (
                                    self.config.orm_provider.get_model_by_name(
                                        current_model_name
                                    )
                                )
                            else:
                                # If not a relation, we can't go deeper
                                break
            else:
                # This is a simple field
                fields_map[model_name].add(field)

        return fields_map

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
        if "selectRelated" in ast and isinstance(ast["selectRelated"], list):
            self.engine.select_related(ast["selectRelated"])
        if "prefetchRelated" in ast and isinstance(ast["prefetchRelated"], list):
            self.engine.prefetch_related(ast["prefetchRelated"])

    def _apply_filter(self, ast: Dict[str, Any]) -> None:
        """Apply filter from AST to the queryset."""
        if "filter" in ast and ast["filter"]:
            self.engine.filter_node(ast["filter"])

    def _apply_exclude(self, ast: Dict[str, Any]) -> None:
        """Apply exclude from AST to the queryset."""
        if "exclude" in ast and ast["exclude"]:
            self.engine.exclude_node(ast["exclude"])

    def _apply_ordering(self, ast: Dict[str, Any]) -> None:
        if "orderBy" in ast:
            self.engine.order_by(ast["orderBy"])

    def _apply_field_selection(self, ast: Dict[str, Any]) -> None:
        if "fields" in ast and isinstance(ast["fields"], list):
            self.engine.select_fields(ast["fields"])

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
            final_search_fields = config_search_fields.intersection(set(frontend_fields))
        else:
            final_search_fields = config_search_fields

        # Delegate to the ORM adapter's search_node() method.
        self.engine.search_node(search_query, final_search_fields)

    # --- Operation Handlers with Hard-Coded Response Types ---

    def _handle_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        data = ast.get("data", {})
        validated_data = self.serializer.deserialize(
            model=self.model, data=data, partial=False
        )
        record = self.engine.create(validated_data, self.serializer)
        serialized = self.serializer.serialize(
            record, self.model, many=False, **self.ser_args
        )
        return {
            "data": serialized,
            "metadata": {"created": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_update(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        data = ast.get("data", {})
        validated_data = self.serializer.deserialize(
            model=self.model, data=data, partial=True
        )
        ast["data"] = validated_data
        # Retrieve permissions from the self.registry.
        permissions = self.registry.get_config(self.model).permissions
        rows_updated = self.engine.update(ast, self.request, permissions)
        return {
            "data": None,
            "metadata": {
                "updated": True,
                "rows_updated": rows_updated,
                "response_type": ResponseType.NUMBER.value,
            },
        }

    def _handle_delete(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        permissions = self.registry.get_config(self.model).permissions
        rows_deleted = self.engine.delete(ast, self.request, permissions)
        return {
            "data": None,
            "metadata": {
                "deleted": True,
                "rows_deleted": rows_deleted,
                "response_type": ResponseType.NUMBER.value,
            },
        }

    def _handle_update_instance(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        # Extract and deserialize the data.
        raw_data = ast.get("data", {})
        # Allow partial updates.
        validated_data = self.serializer.deserialize(
            model=self.model, data=raw_data, partial=True
        )
        # Replace raw data with validated data in the AST.
        ast["data"] = validated_data

        # Retrieve permissions from the self.registry.
        permissions = self.registry.get_config(self.model).permissions

        # Delegate to the engine's instance-based update method.
        updated_instance = self.engine.update_instance(ast, self.request, permissions, self.serializer)

        # Serialize the updated instance for the response.
        serialized = self.serializer.serialize(
            updated_instance, self.model, many=False, **self.ser_args
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
        deleted_count = self.engine.delete_instance(ast, self.request, permissions)

        return {
            "data": deleted_count,
            "metadata": {"deleted": True, "response_type": ResponseType.BOOLEAN.value},
        }

    def _handle_get(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        # Retrieve permissions from the registry
        permissions = self.registry.get_config(self.model).permissions
        record = self.engine.get(ast, self.request, permissions)
        serialized = self.serializer.serialize(
            record, self.model, many=False, **self.ser_args
        )
        return {
            "data": serialized,
            "metadata": {"get": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_get_or_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        # Validate and split lookup/defaults (without extra wrapping)
        self._validate_and_split_lookup_defaults(ast, partial=False)

        # Merge lookup and defaults.
        merged_data = {**ast.get("lookup", {}), **ast.get("defaults", {})}

        # Optionally update the AST if needed:
        ast["lookup"] = ast.get("lookup", {})
        ast["defaults"] = ast.get("defaults", {})

        # Retrieve permissions from configuration
        permissions = self.registry.get_config(self.model).permissions

        # Call the ORM layer and pass the serializer and request/permissions
        record, created = self.engine.get_or_create(
            {"lookup": ast.get("lookup", {}), "defaults": ast.get("defaults", {})},
            serializer=self.serializer,
            req=self.request,
            permissions=permissions,
        )

        serialized = self.serializer.serialize(
            record, self.model, many=False, **self.ser_args
        )
        return {
            "data": serialized,
            "metadata": {
                "created": created,
                "response_type": ResponseType.INSTANCE.value,
            },
        }

    def _handle_update_or_create(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        # Validate and split lookup/defaults.
        self._validate_and_split_lookup_defaults(ast, partial=False)

        # Merge lookup and defaults for full validation.
        merged_data = {**ast.get("lookup", {}), **ast.get("defaults", {})}

        # Optionally update the AST if needed:
        ast["lookup"] = ast.get("lookup", {})
        ast["defaults"] = ast.get("defaults", {})

        # Retrieve permissions from configuration.
        permissions = self.registry.get_config(self.model).permissions

        # Call the ORM update_or_create method, passing the serializer, request, and permissions.
        record, created = self.engine.update_or_create(
            {"lookup": ast.get("lookup", {}), "defaults": ast.get("defaults", {})},
            request=self.request,
            serializer=self.serializer,
            permissions=permissions,
        )

        serialized = self.serializer.serialize(
            record, self.model, many=False, **self.ser_args
        )
        return {
            "data": serialized,
            "metadata": {
                "created": created,
                "response_type": ResponseType.INSTANCE.value,
            },
        }

    def _handle_first(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        record = self.engine.first()
        serialized = self.serializer.serialize(
            record, self.model, many=False, **self.ser_args
        )
        return {
            "data": serialized,
            "metadata": {"first": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_last(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        record = self.engine.last()
        serialized = self.serializer.serialize(
            record, self.model, many=False, **self.ser_args
        )
        return {
            "data": serialized,
            "metadata": {"last": True, "response_type": ResponseType.INSTANCE.value},
        }

    def _handle_exists(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        exists_flag = self.engine.exists()
        return {
            "data": exists_flag,
            "metadata": {"exists": True, "response_type": ResponseType.NUMBER.value},
        }

    def _handle_aggregate(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        op_type = ast.get("type")
        if op_type == "aggregate":
            aggs = ast.get("aggregates", {})
            agg_list = []
            for func, field in aggs.items():
                agg_list.append(
                    {"function": func, "field": field, "alias": f"{field}_{func}"}
                )
            result = self.engine.aggregate(agg_list)
            return {
                "data": result,
                "metadata": {
                    "aggregate": True,
                    "response_type": ResponseType.NUMBER.value,
                },
            }
        else:
            field = ast.get("field")
            if not field:
                raise ValueError("Field must be provided for aggregate operations.")
            if op_type == "count":
                result_val = self.engine.count(field)
                return {
                    "data": result_val,
                    "metadata": {
                        "count": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }
            elif op_type == "sum":
                result_val = self.engine.sum(field)
                return {
                    "data": result_val,
                    "metadata": {
                        "sum": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }
            elif op_type == "avg":
                result_val = self.engine.avg(field)
                return {
                    "data": result_val,
                    "metadata": {
                        "avg": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }
            elif op_type == "min":
                result_val = self.engine.min(field)
                return {
                    "data": result_val,
                    "metadata": {
                        "min": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }
            elif op_type == "max":
                result_val = self.engine.max(field)
                return {
                    "data": result_val,
                    "metadata": {
                        "max": True,
                        "response_type": ResponseType.NUMBER.value,
                    },
                }

    def _handle_read(self, ast: Dict[str, Any]) -> Dict[str, Any]:
        offset_raw = self.serializer_options.get("offset", 0)
        limit_raw = self.serializer_options.get("limit", self.config.default_limit)
        offset_val = int(offset_raw) if offset_raw is not None else None
        limit_val = int(limit_raw) if limit_raw is not None else None

        # Retrieve permissions from configuration
        permissions = self.registry.get_config(self.model).permissions

        # Fetch list with bulk permission checks
        rows = self.engine.fetch_list(
            offset=offset_val,
            limit=limit_val,
            req=self.request,
            permissions=permissions,
        )

        serialized = self.serializer.serialize(
            rows, self.model, many=True, **self.ser_args
        )
        return {
            "data": serialized,
            "metadata": {"read": True, "response_type": ResponseType.QUERYSET.value},
        }

    # --- Helper Methods ---

    def _validate_and_split_lookup_defaults(
        self, ast: Dict[str, Any], partial: bool = False
    ) -> None:
        raw_lookup = ast.get("lookup", {})
        raw_defaults = ast.get("defaults", {})
        combined_data = {**raw_lookup, **raw_defaults}
        validated_data = self.serializer.deserialize(
            model=self.model, data=combined_data, partial=partial
        )
        validated_lookup = {
            k: validated_data[k] for k in raw_lookup if k in validated_data
        }
        validated_defaults = {
            k: validated_data[k] for k in raw_defaults if k in validated_data
        }
        ast["lookup"] = validated_lookup
        ast["defaults"] = validated_defaults

    def _maybe_serialize_data(self, data: Union[ORMModel, Any]) -> Any:  # type:ignore
        if data is None:
            return None
        if isinstance(data, self.model):
            return self.serializer.serialize(
                data, self.model, many=False, **self.ser_args
            )
        return self.serializer.serialize(data, self.model, many=True, **self.ser_args)

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
