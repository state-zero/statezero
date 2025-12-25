import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union

import networkx as nx
from django.apps import apps
from django.db import models
from django.db.models import Avg, Count, Max, Min, Q, Sum, QuerySet
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver
from rest_framework import serializers


from statezero.adaptors.django.config import config, registry
from statezero.core.classes import FieldNode, ModelNode
from statezero.core.event_bus import EventBus
from statezero.core.exceptions import (
    MultipleObjectsReturned,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from statezero.core.interfaces import (
    AbstractCustomQueryset,
    AbstractORMProvider,
    AbstractPermission,
)
from statezero.core.types import ActionType, RequestType
from statezero.adaptors.django.serializers import get_custom_serializer

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# -------------------------------------------------------------------
# AST Visitor for Django (builds Django Q objects)
# -------------------------------------------------------------------
class QueryASTVisitor:
    SUPPORTED_OPERATORS: Set[str] = {
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

    def __init__(self, model: Type[models.Model]) -> None:
        self.model = model

    def visit(self, node: Dict[str, Any]) -> Q:
        """Process an AST node and return a Django Q object."""
        if not node:
            return Q()

        node_type: str = node.get("type")
        if not node_type:
            # Handle implicit filter nodes (raw dict conditions)
            if isinstance(node, dict) and "conditions" in node:
                return self.visit_filter(node)
            return Q()

        method = getattr(self, f"visit_{node_type}", None)
        if not method:
            raise ValidationError(f"Unsupported AST node type: {node_type}")
        return method(node)

    def _combine(
        self, children: List[Dict[str, Any]], combine_func: Callable[[Q, Q], Q]
    ) -> Q:
        """Combine multiple Q objects using the provided function (AND/OR)."""
        if not children:
            return Q()  # Return an identity filter when no children exist.
        q = self.visit(children[0])
        for child in children[1:]:
            q = combine_func(q, self.visit(child))
        return q

    def _process_field_lookup(self, field: str, value: Any) -> Tuple[str, Any]:
        """
        This used to contain logic, right now it just passes through the field and value.

        Args:
            field: The field lookup string (e.g., 'datetime_field__hour__gt')
            value: The value to filter by

        Returns:
            A tuple of (lookup, value)
        """
        return field, value

    def visit_filter(self, node: Dict[str, Any]) -> Q:
        """Process a filter node, handling both conditions and Q objects."""
        q = Q()

        # Process direct conditions
        conditions: Dict[str, Any] = node.get("conditions", {})
        for field, value in conditions.items():
            lookup, processed_value = self._process_field_lookup(field, value)
            q &= Q(**{lookup: processed_value})

        # Handle Q list format for OR conditions
        q_objects = node.get("Q", [])
        if q_objects:
            q_combined = None
            for q_condition in q_objects:
                q_part = Q()
                for field, value in q_condition.items():
                    lookup, processed_value = self._process_field_lookup(field, value)
                    q_part &= Q(**{lookup: processed_value})
                if q_combined is None:
                    q_combined = q_part
                else:
                    q_combined |= q_part
            if q_combined:
                q &= q_combined
        return q

    def visit_exclude(self, node: Dict[str, Any]) -> Q:
        """Process an exclude node by negating the inner filter."""
        # Handle child nodes if present
        if "child" in node and node["child"]:
            inner_q = self.visit(node["child"])
            return ~inner_q

        # Otherwise, treat it as a filter but negate the result
        return ~self.visit_filter(node)

    def visit_and(self, node: Dict[str, Any]) -> Q:
        """Process an AND node by combining all children with AND."""
        return self._combine(node.get("children", []), lambda a, b: a & b)

    def visit_or(self, node: Dict[str, Any]) -> Q:
        """Process an OR node by combining all children with OR."""
        return self._combine(node.get("children", []), lambda a, b: a | b)

    def visit_search(self, node: Dict[str, Any]) -> Q:
        """
        Process a search node.
        Since search is applied as a query modifier in the AST parser and via the ORM adapter,
        simply return an empty Q object.
        """
        return Q()


# -------------------------------------------------------------------
# Django ORM Adapter (implements our generic engine/provider)
# -------------------------------------------------------------------
def check_object_permissions(
    req: Any,
    instance: Any,
    action: ActionType,
    permissions: List[Type[AbstractPermission]],
    model: Type,
) -> None:
    """
    Check if the given action is allowed on the instance using each permission class.
    Raises PermissionDenied if none of the permissions grant access.
    """
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
    items: models.QuerySet,
    action: ActionType,
    permissions: List[Type[AbstractPermission]],
    model: Type,
) -> None:
    """
    If the queryset contains one or fewer items, perform individual permission checks.
    Otherwise, loop over permission classes and call bulk_operation_allowed.
    If none allow the bulk operation, raise PermissionDenied.
    """
    if items.count() <= 1:
        for instance in items:
            check_object_permissions(req, instance, action, permissions, model)
    else:
        allowed = False
        for perm_cls in permissions:
            perm = perm_cls()
            # Assume bulk_operation_allowed is defined on all permission classes.
            if perm.bulk_operation_allowed(req, items, action, model):
                allowed = True
                break
        if not allowed:
            raise PermissionDenied(
                f"Bulk {action.value} operation not permitted on queryset"
            )


class DjangoORMAdapter(AbstractORMProvider):
    def __init__(self) -> None:
        # No instance state - completely stateless
        pass

    # --- QueryEngine Methods ---
    def filter_node(self, queryset: QuerySet, node: Dict[str, Any]) -> QuerySet:
        """Apply a filter node to the queryset and return new queryset."""
        model = queryset.model
        visitor = QueryASTVisitor(model)
        q_object = visitor.visit(node)
        return queryset.filter(q_object)

    def search_node(
        self, queryset: QuerySet, search_query: str, search_fields: Set[str]
    ) -> QuerySet:
        """
        Apply a full-text search to the queryset and return new queryset.
        Uses the search_provider from the global configuration.
        """
        return config.search_provider.search(queryset, search_query, search_fields)

    def exclude_node(self, queryset: QuerySet, node: Dict[str, Any]) -> QuerySet:
        """Apply an exclude node to the queryset and return new queryset."""
        model = queryset.model
        visitor = QueryASTVisitor(model)

        # Handle both direct exclude nodes and exclude nodes with a child filter
        if "child" in node:
            # If there's a child node, visit it and exclude the result
            q_object = visitor.visit(node["child"])
        else:
            # Otherwise, treat it as a standard filter node to be negated
            q_object = visitor.visit(node)

        return queryset.exclude(q_object)

    def create(
        self,
        model: Type[models.Model],
        data: Dict[str, Any],
        serializer,
        req,
        fields_map,
    ) -> models.Model:
        """Create a new model instance."""
        # Use the provided serializer's save method
        return serializer.save(
            model=model,
            data=data,
            instance=None,
            partial=False,
            request=req,
            fields_map=fields_map,
        )

    def bulk_create(
        self,
        model: Type[models.Model],
        data_list: List[Dict[str, Any]],
        serializer,
        req,
        fields_map,
    ) -> List[models.Model]:
        """Create multiple model instances using Django's bulk_create."""
        # Create instances without saving to DB yet
        instances = [model(**data) for data in data_list]

        # Use Django's bulk_create for efficiency
        created_instances = model.objects.bulk_create(instances)

        # Emit bulk create event for cache invalidation and frontend notification
        config.event_bus.emit_bulk_event(ActionType.BULK_CREATE, created_instances)

        return created_instances

    def update_instance(
        self,
        model: Type[models.Model],
        ast: Dict[str, Any],
        req: RequestType,
        permissions: List[Type[AbstractPermission]],
        serializer,
        fields_map,
    ) -> models.Model:
        """Update a single model instance."""
        data = ast.get("data", {})
        filter_ast = ast.get("filter")
        if not filter_ast:
            raise ValueError("Filter is required for update_instance operation")

        visitor = QueryASTVisitor(model)
        q_obj = visitor.visit(filter_ast)
        instance = model.objects.get(q_obj)

        # Check object-level permissions for update.
        for perm_cls in permissions:
            perm = perm_cls()
            allowed = perm.allowed_object_actions(req, instance, model)
            if ActionType.UPDATE not in allowed:
                raise PermissionDenied(f"Update not permitted on {instance}")

        # Use the provided serializer's save method for the update
        return serializer.save(
            model=model,
            data=data,
            instance=instance,
            partial=True,
            request=req,
            fields_map=fields_map,
        )

    def delete_instance(
        self,
        model: Type[models.Model],
        ast: Dict[str, Any],
        req: RequestType,
        permissions: List[Type[AbstractPermission]],
    ) -> int:
        """Delete a single model instance."""
        filter_ast = ast.get("filter")
        if not filter_ast:
            raise ValueError("Filter is required for delete_instance operation")

        visitor = QueryASTVisitor(model)
        q_obj = visitor.visit(filter_ast)
        instance = model.objects.get(q_obj)

        # Check object-level permissions.
        for perm_cls in permissions:
            perm = perm_cls()
            allowed = perm.allowed_object_actions(req, instance, model)
            if ActionType.DELETE not in allowed:
                raise PermissionDenied(f"Delete not permitted on {instance}")

        instance.delete()
        return 1

    @staticmethod
    def get_pk_list(queryset: QuerySet) -> List[Any]:
        """
        Gets a list of primary key values from a QuerySet, handling different PK field names.

        Args:
            queryset: The Django QuerySet.

        Returns:
            A list of primary key values.
        """
        model = queryset.model
        pk_field_name = model._meta.pk.name  # Dynamically get the PK field name
        pk_list = queryset.values_list(pk_field_name, flat=True)
        return list(pk_list)

    def update(
        self,
        queryset: QuerySet,
        node: Dict[str, Any],
        req: RequestType,
        permissions: List[Type[AbstractPermission]],
        readable_fields: Set[str] = None,
    ) -> Tuple[int, List[Dict[str, Union[int, str]]]]:
        """
        Update operations with support for F expressions.
        Includes permission checks for fields referenced in F expressions.
        """
        model = queryset.model
        data: Dict[str, Any] = node.get("data", {})
        filter_ast: Optional[Dict[str, Any]] = node.get("filter")

        # Start with the provided queryset which already has permission filtering
        qs: QuerySet = queryset
        if filter_ast:
            visitor = QueryASTVisitor(model)
            q_obj = visitor.visit(filter_ast)
            qs = qs.filter(q_obj)

        # Check bulk update permissions
        check_bulk_permissions(req, qs, ActionType.UPDATE, permissions, model)

        # Get the fields to update (keys from data plus primary key)
        update_fields = list(data.keys())
        update_fields.append(model._meta.pk.name)

        # Process any F expressions in the update data
        processed_data = {}
        from statezero.adaptors.django.f_handler import FExpressionHandler

        for key, value in data.items():
            if isinstance(value, dict) and value.get("__f_expr"):
                # It's an F expression - check permissions and process it
                try:
                    # Extract field names referenced in the F expression
                    referenced_fields = FExpressionHandler.extract_referenced_fields(
                        value
                    )

                    # Check that user has READ permissions for all referenced fields
                    for field in referenced_fields:
                        if field not in readable_fields:
                            raise PermissionDenied(
                                f"No permission to read field '{field}' referenced in F expression"
                            )

                    # Process the F expression now that permissions are verified
                    processed_data[key] = FExpressionHandler.process_expression(value)
                except ValueError as e:
                    logger.error(f"Error processing F expression for field {key}: {e}")
                    raise ValidationError(
                        f"Invalid F expression for field {key}: {str(e)}"
                    )
            else:
                # Regular value, use as-is
                processed_data[key] = value

        # Execute the update with processed expressions
        rows_updated = qs.update(**processed_data)

        # Expand update_fields to include all DB fields for custom serializers (e.g., MoneyField)
        # This ensures .only() fetches companion fields like price_currency for MoneyField
        expanded_update_fields = set()
        for field_name in update_fields:
            try:
                field_obj = model._meta.get_field(field_name)
                if not field_obj.is_relation:
                    custom_serializer = get_custom_serializer(field_obj.__class__)
                    if custom_serializer and hasattr(custom_serializer, 'get_prefetch_db_fields'):
                        db_fields = custom_serializer.get_prefetch_db_fields(field_name)
                        expanded_update_fields.update(db_fields)
                    else:
                        expanded_update_fields.add(field_name)
                else:
                    expanded_update_fields.add(field_name)
            except Exception:
                # If field lookup fails, include as-is
                expanded_update_fields.add(field_name)

        # After update, fetch the updated instances
        updated_instances = list(qs.only(*expanded_update_fields))

        # Triggers cache invalidation and broadcast to the frontend
        config.event_bus.emit_bulk_event(ActionType.BULK_UPDATE, updated_instances)

        return rows_updated, updated_instances

    def delete(
        self,
        queryset: QuerySet,
        node: Dict[str, Any],
        req: RequestType,
        permissions: List[Type[AbstractPermission]],
    ) -> Tuple[int, Tuple[int]]:
        """Delete multiple model instances."""
        model = queryset.model
        filter_ast: Optional[Dict[str, Any]] = node.get("filter")
        # Start with the provided queryset which already has permission filtering
        qs: QuerySet = queryset
        if filter_ast:
            visitor = QueryASTVisitor(model)
            q_obj = visitor.visit(filter_ast)
            qs = qs.filter(q_obj)

        check_bulk_permissions(req, qs, ActionType.DELETE, permissions, model)

        # TODO: this should be a values list, but we need to check the bulk event emitter code
        pk_field_name = model._meta.pk.name
        instances = list(qs.only(pk_field_name))

        deleted, _ = qs.delete()

        # Triggers cache invalidation and broadcast to the frontend
        config.event_bus.emit_bulk_event(ActionType.BULK_DELETE, instances)

        # Dynamically create a Meta inner class
        Meta = type(
            "Meta",
            (),
            {
                "model": model,
                "fields": [pk_field_name],  # Only include the PK field
            },
        )

        # Create the serializer class
        serializer_class = type(
            f"Dynamic{model.__name__}PkSerializer",
            (serializers.ModelSerializer,),
            {"Meta": Meta},
        )

        serializer = serializer_class(instances, many=True)

        return deleted, serializer.data

    def get(
        self,
        queryset: QuerySet,
        node: Dict[str, Any],
        req: RequestType,
        permissions: List[Type[AbstractPermission]],
    ) -> models.Model:
        """
        Retrieve a single model instance with permission checks.

        Args:
            queryset: The base queryset to search in
            node: The query AST node
            req: The request object
            permissions: List of permission classes to check

        Returns:
            A single model instance

        Raises:
            NotFound: If no object matches the query
            PermissionDenied: If the user doesn't have permission to read the object
            MultipleObjectsReturned: If multiple objects match the query
        """
        model = queryset.model
        filter_ast: Optional[Dict[str, Any]] = node.get("filter")

        if filter_ast:
            visitor = QueryASTVisitor(model)
            q_obj = visitor.visit(filter_ast)
            try:
                instance = queryset.filter(q_obj).get()
            except model.DoesNotExist:
                raise NotFound(f"No {model.__name__} matches the given query.")
            except model.MultipleObjectsReturned:
                raise MultipleObjectsReturned(
                    f"Multiple {model.__name__} instances match the given query."
                )
        else:
            try:
                instance = queryset.get()
            except model.DoesNotExist:
                raise NotFound(f"No {model.__name__} matches the given query.")
            except model.MultipleObjectsReturned:
                raise MultipleObjectsReturned(
                    f"Multiple {model.__name__} instances match the given query."
                )

        # Check object-level permissions for reading
        check_object_permissions(req, instance, ActionType.READ, permissions, model)

        return instance

    def _normalize_foreign_keys(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        For each key in data, if the value is a model instance, replace it with its primary key.
        """
        normalized = {}
        for key, value in data.items():
            # Check for model instance by looking for the _meta attribute.
            if hasattr(value, "_meta"):
                normalized[key] = value.pk
            else:
                normalized[key] = value
        return normalized

    def get_or_create(
        self,
        queryset: QuerySet,
        node: Dict[str, Any],
        serializer,
        req: RequestType,
        permissions: List[Type[AbstractPermission]],
        create_fields_map,
    ) -> Tuple[models.Model, bool]:
        """
        Get an existing object, or create it if it doesn't exist, with object-level permission checks.
        """
        model = queryset.model
        lookup = node.get("lookup", {})
        defaults = node.get("defaults", {})

        # Merge lookup and defaults and normalize foreign key values
        merged_data = self._normalize_foreign_keys({**lookup, **defaults})

        # Check if an instance exists
        try:
            instance = queryset.get(**lookup)
            created = False

            # Check object-level permission to read the existing object
            check_object_permissions(req, instance, ActionType.READ, permissions, model)
        except model.DoesNotExist:
            # Object doesn't exist, we'll create it
            instance = None
            created = True
        except model.MultipleObjectsReturned as e:
            raise MultipleObjectsReturned(
                f"Multiple {model.__name__} instances match the given lookup parameters"
            )

        # If the instance exists, we don't need to update it, just return it
        if not created:
            return instance, created

        # Only create a new instance if it doesn't exist
        instance = serializer.save(
            model=model,
            data=merged_data,
            instance=None,  # No instance for creation
            partial=False,  # Not a partial update for creation
            request=req,
            fields_map=create_fields_map,
        )

        return instance, created

    def update_or_create(
        self,
        queryset: QuerySet,
        node: Dict[str, Any],
        req: RequestType,
        serializer,
        permissions: List[Type[AbstractPermission]],
        update_fields_map,
        create_fields_map,
    ) -> Tuple[models.Model, bool]:
        """
        Update an existing object, or create it if it doesn't exist, with object-level permission checks.
        """
        model = queryset.model
        lookup = node.get("lookup", {})
        defaults = node.get("defaults", {})

        # Merge lookup and defaults and normalize foreign key values
        merged_data = self._normalize_foreign_keys({**lookup, **defaults})

        # Determine if the instance exists
        try:
            instance = queryset.get(**lookup)
            created = False

            # Perform object-level permission check before update
            check_object_permissions(
                req, instance, ActionType.UPDATE, permissions, model
            )
        except model.DoesNotExist:
            # Object doesn't exist, we'll create it
            instance = None
            created = True
        except model.MultipleObjectsReturned as e:
            raise MultipleObjectsReturned(
                f"Multiple {model.__name__} instances match the given lookup parameters"
            )

        fields_map_to_use = create_fields_map if created else update_fields_map

        # Use the serializer's save method, which handles validation and saving
        instance = serializer.save(
            model=model,
            data=merged_data,
            instance=instance,
            request=req,
            fields_map=fields_map_to_use,
        )

        return instance, created

    def first(self, queryset: QuerySet) -> Optional[models.Model]:
        """Return the first record from the queryset."""
        return queryset.first()

    def last(self, queryset: QuerySet) -> Optional[models.Model]:
        """Return the last record from the queryset."""
        return queryset.last()

    def exists(self, queryset: QuerySet) -> bool:
        """Return True if the queryset has any results; otherwise False."""
        return queryset.exists()

    def aggregate(
        self, queryset: QuerySet, agg_list: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Perform aggregation operations on the queryset."""
        agg_expressions = {}
        for agg in agg_list:
            func = agg.get("function")
            field = agg.get("field")
            alias = agg.get("alias")
            if func == "count":
                agg_expressions[alias] = Count(field)
            elif func == "sum":
                agg_expressions[alias] = Sum(field)
            elif func == "avg":
                agg_expressions[alias] = Avg(field)
            elif func == "min":
                agg_expressions[alias] = Min(field)
            elif func == "max":
                agg_expressions[alias] = Max(field)
            else:
                raise ValidationError(f"Unknown aggregate function: {func}")
        result = queryset.aggregate(**agg_expressions)
        return {"data": result, "metadata": {"aggregated": True}}

    def count(self, queryset: QuerySet, field: str) -> int:
        """Count the number of records for the given field."""
        result = queryset.aggregate(result=Count(field))["result"]
        return int(result) if result is not None else 0

    def sum(self, queryset: QuerySet, field: str) -> Optional[Union[int, float]]:
        """Sum the values of the given field."""
        return queryset.aggregate(result=Sum(field))["result"]

    def avg(self, queryset: QuerySet, field: str) -> Optional[float]:
        """Calculate the average of the given field."""
        result = queryset.aggregate(result=Avg(field))["result"]
        return float(result) if result is not None else None

    def min(self, queryset: QuerySet, field: str) -> Optional[Union[int, float, str]]:
        """Find the minimum value for the given field."""
        return queryset.aggregate(result=Min(field))["result"]

    def max(self, queryset: QuerySet, field: str) -> Optional[Union[int, float, str]]:
        """Find the maximum value for the given field."""
        return queryset.aggregate(result=Max(field))["result"]

    def order_by(self, queryset: QuerySet, order_list: List[str]) -> QuerySet:
        """Order the queryset based on a list of fields."""
        return queryset.order_by(*order_list)

    def select_related(self, queryset: QuerySet, related_fields: List[str]) -> QuerySet:
        """Optimize the queryset by eager loading the given related fields."""
        return queryset.select_related(*related_fields)

    def prefetch_related(
        self, queryset: QuerySet, related_fields: List[str]
    ) -> QuerySet:
        """Optimize the queryset by prefetching the given related fields."""
        return queryset.prefetch_related(*related_fields)

    def select_fields(self, queryset: QuerySet, fields: List[str]) -> QuerySet:
        """Select only specific fields from the queryset."""
        return queryset.values(*fields)

    def fetch_list(
        self,
        queryset: QuerySet,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        req: RequestType = None,
        permissions: List[Type[AbstractPermission]] = None,
    ) -> QuerySet:
        """
        Fetch a list of model instances with bulk permission checks.

        Args:
            queryset: The queryset to paginate
            offset: The offset for pagination
            limit: The limit for pagination
            req: The request object
            permissions: List of permission classes to check

        Returns:
            A sliced queryset after permission checks
        """
        model = queryset.model
        offset = offset or 0

        # FIXED: Perform bulk permission checks BEFORE slicing
        if req is not None and permissions:
            # Use the existing bulk permission check function on the unsliced queryset
            check_bulk_permissions(req, queryset, ActionType.READ, permissions, model)

        # THEN apply pagination/slicing
        if limit is None:
            qs = queryset[offset:]
        else:
            qs = queryset[offset : offset + limit]

        return qs

    def _build_conditions(self, model: Type[models.Model], conditions: dict) -> Q:
        """Build Q conditions from a dictionary."""
        visitor = QueryASTVisitor(model)
        fake_ast = {"type": "filter", "conditions": conditions}
        return visitor.visit(fake_ast)

    # --- AbstractORMProvider Methods ---
    def get_queryset(
        self,
        req: RequestType,
        model: Type,
        initial_ast: Dict[str, Any],
        registered_permissions: List[Type[AbstractPermission]],
    ) -> Any:
        """Assemble and return the base QuerySet for the given model."""
        return model.objects.all()

    def get_fields(self, model: models.Model) -> Set[str]:
        """
        Return a set of the model fields.
        Includes both database fields and additional_fields (computed fields).
        """
        model_config = registry.get_config(model)
        if model_config.fields and "__all__" != model_config.fields:
            resolved_fields = model_config.fields
        else:
            resolved_fields = set((field.name for field in model._meta.get_fields()))
            additional_fields = set(
                (field.name for field in model_config.additional_fields)
            )
            resolved_fields = resolved_fields.union(additional_fields)
        return resolved_fields

    def get_db_fields(self, model: models.Model) -> Set[str]:
        """
        Return only actual database fields for the model.
        Excludes read-only additional_fields (computed fields).
        Used for deserialization - hooks can write to any DB field.
        """
        return set(field.name for field in model._meta.get_fields())

    def build_model_graph(
        self, model: Type[models.Model], model_graph: nx.DiGraph = None
    ) -> nx.DiGraph:
        """
        Build a directed graph of models and their fields, focusing on direct relationships.

        Args:
            model: The Django model to build the graph for
            model_graph: An existing graph to add to (optional)

        Returns:
            nx.DiGraph: The model graph
        """
        from django.db.models.fields.related import RelatedField, ForeignObjectRel

        if model_graph is None:
            model_graph = nx.DiGraph()

        # Use the adapter's get_model_name method.
        model_name = self.get_model_name(model)

        # Add the model node if it doesn't exist.
        if not model_graph.has_node(model_name):
            model_graph.add_node(
                model_name, data=ModelNode(model_name=model_name, model=model)
            )

        # Iterate over all fields in the model.
        for field in model._meta.get_fields():
            field_name = field.name

            # Handle reverse relations - only include if explicitly configured in fields
            if isinstance(field, ForeignObjectRel):
                # Check if this reverse relation is explicitly listed in the model's fields config
                try:
                    model_config = registry.get_config(model)
                    configured_fields = model_config.fields
                    # Skip if fields is "__all__" (we don't auto-include reverse relations)
                    # or if the field is not explicitly in the configured fields set
                    if configured_fields == "__all__" or field_name not in configured_fields:
                        continue
                except ValueError:
                    # Model not registered, skip reverse relation
                    continue

                # For reverse relations, the related model is the model that defines the FK
                related_model = field.related_model
                related_model_name = self.get_model_name(related_model)

                field_node = f"{model_name}::{field_name}"
                field_node_data = FieldNode(
                    model_name=model_name,
                    field_name=field_name,
                    is_relation=True,
                    related_model=related_model_name,
                )
                model_graph.add_node(field_node, data=field_node_data)
                model_graph.add_edge(model_name, field_node)

                # Recursively build the related model if not already in the graph
                if not model_graph.has_node(related_model_name):
                    self.build_model_graph(related_model, model_graph)
                model_graph.add_edge(field_node, related_model_name)
                continue

            field_node = f"{model_name}::{field_name}"
            field_node_data = FieldNode(
                model_name=model_name,
                field_name=field_name,
                is_relation=field.is_relation,
                related_model=(
                    self.get_model_name(field.related_model)
                    if field.is_relation and field.related_model
                    else None
                ),
            )
            model_graph.add_node(field_node, data=field_node_data)
            model_graph.add_edge(model_name, field_node)

            if field.is_relation and field.related_model:
                related_model = field.related_model
                related_model_name = self.get_model_name(related_model)
                if not model_graph.has_node(related_model_name):
                    self.build_model_graph(related_model, model_graph)
                model_graph.add_edge(field_node, related_model_name)

        # Add additional (computed) fields from the model's configuration.
        try:
            config = registry.get_config(model)
            for additional_field in config.additional_fields:
                add_field_name = additional_field.name
                add_field_node = f"{model_name}::{add_field_name}"
                is_rel = False
                related_model_name = None
                if isinstance(
                    additional_field.field,
                    (models.ForeignKey, models.OneToOneField, models.ManyToManyField),
                ):
                    is_rel = True
                    related = getattr(additional_field.field, "related_model", None)
                    if related:
                        related_model_name = self.get_model_name(related)
                add_field_node_data = FieldNode(
                    model_name=model_name,
                    field_name=add_field_name,
                    is_relation=is_rel,
                    related_model=related_model_name,
                )
                model_graph.add_node(add_field_node, data=add_field_node_data)
                model_graph.add_edge(model_name, add_field_node)
        except ValueError:
            pass

        return model_graph

    def register_event_signals(self, event_bus: EventBus) -> None:
        """Register Django signals for model events."""

        def pre_save_receiver(sender, instance, **kwargs):
            if not instance.pk:
                return  # It can't be used for cache invalidation, cause there's no pk

            action = ActionType.PRE_UPDATE
            try:
                event_bus.emit_event(action, instance)
            except Exception as e:
                logger.exception(
                    "Error emitting event %s for instance %s: %s", action, instance, e
                )

        def post_save_receiver(sender, instance, created, **kwargs):
            action = ActionType.CREATE if created else ActionType.UPDATE
            try:
                event_bus.emit_event(action, instance)
            except Exception as e:
                logger.exception(
                    "Error emitting event %s for instance %s: %s", action, instance, e
                )

        def pre_delete_receiver(sender, instance, **kwargs):
            try:
                # Use PRE_DELETE action type for cache invalidation before DB operation
                event_bus.emit_event(ActionType.PRE_DELETE, instance)
            except Exception as e:
                logger.exception(
                    "Error emitting PRE_DELETE event for instance %s: %s", instance, e
                )

        def post_delete_receiver(sender, instance, **kwargs):
            try:
                event_bus.emit_event(ActionType.DELETE, instance)
            except Exception as e:
                logger.exception(
                    "Error emitting DELETE event for instance %s: %s", instance, e
                )

        from statezero.adaptors.django.config import config, registry

        for model in registry._models_config.keys():
            model_name = config.orm_provider.get_model_name(model)

            # Register pre_save signals (new)
            uid_pre_save = f"statezero:{model_name}:pre_save"
            pre_save.disconnect(sender=model, dispatch_uid=uid_pre_save)
            receiver(pre_save, sender=model, weak=False, dispatch_uid=uid_pre_save)(
                pre_save_receiver
            )

            # Register post_save signals
            uid_save = f"statezero:{model_name}:post_save"
            post_save.disconnect(sender=model, dispatch_uid=uid_save)
            receiver(post_save, sender=model, weak=False, dispatch_uid=uid_save)(
                post_save_receiver
            )

            # Register pre_delete signals
            uid_pre_delete = f"statezero:{model_name}:pre_delete"
            pre_delete.disconnect(sender=model, dispatch_uid=uid_pre_delete)
            receiver(pre_delete, sender=model, weak=False, dispatch_uid=uid_pre_delete)(
                pre_delete_receiver
            )

            # Register post_delete signals
            uid_delete = f"statezero:{model_name}:post_delete"
            post_delete.disconnect(sender=model, dispatch_uid=uid_delete)
            receiver(post_delete, sender=model, weak=False, dispatch_uid=uid_delete)(
                post_delete_receiver
            )

    def get_model_by_name(self, model_name: str) -> Type[models.Model]:
        """Retrieve the model class based on a given model name."""
        try:
            app_label, model_cls = model_name.split(".")
            model = apps.get_model(app_label, model_cls)
            if model is None:
                raise NotFound(f"Unknown model: {model_name}")
            return model
        except ValueError:
            raise NotFound(
                f"Model name '{model_name}' must be in the format 'app_label.ModelName'"
            )

    def get_model_name(self, model: Union[models.Model, Type[models.Model]]) -> str:
        """Retrieve the model name for the given model class or instance."""
        if not isinstance(model, type):
            model = model.__class__
        if hasattr(model, "_meta"):
            return f"{model._meta.app_label}.{model._meta.model_name}"
        raise ValueError(
            f"Cannot determine model name from {model} of type {type(model)}: _meta attribute is missing from the model."
        )

    def get_user(self, request):
        """Return the user from the request."""
        return request.user

    def validate(
        self,
        model: Type[models.Model],
        data: Dict[str, Any],
        validate_type: str,
        partial: bool,
        request: RequestType,
        permissions: List[Type[AbstractPermission]],
        serializer,
    ) -> bool:
        """
        Fast validation without database queries.
        Only checks model-level permissions and serializer validation.

        Args:
            model: Django model class
            data: Data to validate
            validate_type: 'create' or 'update'
            partial: Whether to allow partial validation (only validate provided fields)
            request: Request object
            permissions: Permission classes
            serializer: Serializer instance

        Returns:
            bool: True if validation passes

        Raises:
            ValidationError: For serializer validation failures
            PermissionDenied: For permission failures
        """
        # Basic model-level permission check (no DB query)
        required_action = (
            ActionType.CREATE if validate_type == "create" else ActionType.UPDATE
        )

        has_permission = False
        for permission_class in permissions:
            perm_instance = permission_class()
            allowed_actions = perm_instance.allowed_actions(request, model)
            if required_action in allowed_actions:
                has_permission = True
                break

        if not has_permission:
            # Let StateZero exception handling deal with this
            raise PermissionDenied(f"{validate_type.title()} not allowed")

        # Get field permissions
        allowed_fields = self._get_allowed_fields(
            model, permissions, request, validate_type
        )

        # Filter data to only allowed fields
        filtered_data = {k: v for k, v in data.items() if k in allowed_fields}

        # Create minimal fields map for serializer
        model_name = config.orm_provider.get_model_name(model)
        fields_map = {model_name: allowed_fields}

        # Validate using serializer with partial flag - let ValidationError bubble up naturally
        serializer.deserialize(
            model=model,
            data=filtered_data,
            partial=partial,
            request=request,
            fields_map=fields_map,
        )

        # Only return success case - exceptions handle failures
        return True

    def _get_allowed_fields(
        self,
        model: Type[models.Model],
        permissions: List[Type[AbstractPermission]],
        request: RequestType,
        validate_type: str,
    ) -> Set[str]:
        """Helper to get allowed fields based on validate_type."""
        allowed_fields = set()

        for permission_class in permissions:
            perm_instance = permission_class()

            if validate_type == "create":
                create_fields = perm_instance.create_fields(request, model)
                if create_fields == "__all__":
                    return config.orm_provider.get_fields(model)
                elif isinstance(create_fields, set):
                    allowed_fields.update(create_fields)
            else:  # update
                editable_fields = perm_instance.editable_fields(request, model)
                if editable_fields == "__all__":
                    return config.orm_provider.get_fields(model)
                elif isinstance(editable_fields, set):
                    allowed_fields.update(editable_fields)

        return allowed_fields
