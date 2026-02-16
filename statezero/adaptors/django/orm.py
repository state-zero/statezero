import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models, transaction
from django.db.models import Q, QuerySet
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver
from rest_framework import serializers


from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.event_bus import EventBus
from statezero.core.exceptions import (
    NotFound,
    PermissionDenied,
    ValidationError,
)
from statezero.core.interfaces import AbstractORMProvider
from statezero.core.types import ActionType, RequestType
from statezero.adaptors.django.serializers import get_custom_serializer

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# -------------------------------------------------------------------
# AST Visitor for Django (builds Django Q objects)
# -------------------------------------------------------------------
class QueryASTVisitor:
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

    def visit_filter(self, node: Dict[str, Any]) -> Q:
        """Process a filter node, handling both conditions and Q objects."""
        q = Q()

        # Process direct conditions
        conditions: Dict[str, Any] = node.get("conditions", {})
        for field, value in conditions.items():
            q &= Q(**{field: value})

        # Handle Q list format for OR conditions
        q_objects = node.get("Q", [])
        if q_objects:
            q_combined = None
            for q_condition in q_objects:
                q_part = Q()
                for field, value in q_condition.items():
                    q_part &= Q(**{field: value})
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


# -------------------------------------------------------------------
# Django ORM Adapter (implements our generic engine/provider)
# -------------------------------------------------------------------
class DjangoORMAdapter(AbstractORMProvider):
    def __init__(self) -> None:
        # No instance state - completely stateless
        pass

    # --- QueryEngine Methods ---
    def filter_node(self, queryset: QuerySet, node: Dict[str, Any]) -> QuerySet:
        """Apply a filter node to the queryset and return new queryset."""
        model = queryset.model
        visitor = QueryASTVisitor(model)

        # For top-level AND nodes, apply each child as a separate filter
        # to get Django's chained filter semantics (ANY/ANY for M2M)
        if node.get("type") == "and" and "children" in node:
            for child in node["children"]:
                q_object = visitor.visit(child)
                queryset = queryset.filter(q_object)
            return queryset

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

        # Handle exclude nodes with a child
        if "child" in node:
            child = node["child"]
            # For top-level AND nodes in exclude, apply each as separate exclude
            # to get Django's chained exclude semantics (ANY/ANY for M2M)
            if child.get("type") == "and" and "children" in child:
                for grandchild in child["children"]:
                    q_object = visitor.visit(grandchild)
                    queryset = queryset.exclude(q_object)
                return queryset
            q_object = visitor.visit(child)
        else:
            q_object = visitor.visit(node)

        return queryset.exclude(q_object)

    def update(
        self,
        queryset: QuerySet,
        node: Dict[str, Any],
        req: RequestType,
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

        # Get the fields to update (keys from data plus primary key)
        update_fields = list(data.keys())
        update_fields.append(model._meta.pk.name)

        # Process any F expressions in the update data
        processed_data = {}
        from statezero.adaptors.django.f_handler import FExpressionHandler

        for key, value in data.items():
            # Reject F expressions on M2M fields — they live in a join table, not a column
            if isinstance(value, dict) and value.get("__f_expr"):
                try:
                    field_obj = model._meta.get_field(key)
                    if field_obj.many_to_many:
                        raise ValidationError(
                            f"F expressions cannot be used on ManyToMany field '{key}'"
                        )
                except FieldDoesNotExist:
                    pass

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

        # Separate M2M fields from regular fields since qs.update() can't handle M2M
        m2m_data = {}
        regular_data = {}
        for key, value in processed_data.items():
            try:
                field_obj = model._meta.get_field(key)
                if field_obj.many_to_many:
                    m2m_data[key] = value
                else:
                    regular_data[key] = value
            except Exception:
                regular_data[key] = value

        # Execute the update with regular (non-M2M) fields
        rows_updated = 0
        if regular_data:
            rows_updated = qs.update(**regular_data)

        # Handle M2M fields by setting them on each instance
        if m2m_data:
            instances = list(qs)
            if not rows_updated:
                rows_updated = len(instances)
            for instance in instances:
                for field_name, value in m2m_data.items():
                    getattr(instance, field_name).set(value)

        # Expand update_fields to include all DB fields for custom serializers (e.g., MoneyField)
        # This ensures .only() fetches companion fields like price_currency for MoneyField
        # Remove M2M fields from update_fields since .only() doesn't support them
        non_m2m_update_fields = [f for f in update_fields if f not in m2m_data]
        expanded_update_fields = set()
        for field_name in non_m2m_update_fields:
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
        if expanded_update_fields:
            updated_instances = list(qs.only(*expanded_update_fields))
        else:
            updated_instances = list(qs)

        # Triggers cache invalidation and broadcast to the frontend
        config.event_bus.emit_bulk_event(ActionType.BULK_UPDATE, updated_instances)

        return rows_updated, updated_instances

    def delete(
        self,
        queryset: QuerySet,
        node: Dict[str, Any],
        req: RequestType,
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

    # --- AbstractORMProvider Methods ---
    def get_queryset(
        self,
        req: RequestType,
        model: Type,
        initial_ast: Dict[str, Any],
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

    def is_nested_path_field(self, model: models.Model, field_name: str) -> bool:
        """
        Check if a field allows arbitrary nested path traversal (e.g., JSONField).
        """
        try:
            field = model._meta.get_field(field_name)
            return isinstance(field, models.JSONField)
        except Exception:
            return False

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
                # Emit after commit so clients don't re-fetch stale rows.
                transaction.on_commit(lambda: event_bus.emit_event(action, instance))
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
                # Emit after commit so clients don't re-fetch stale rows.
                transaction.on_commit(
                    lambda: event_bus.emit_event(ActionType.DELETE, instance)
                )
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
        serializer,
    ) -> bool:
        """
        Fast validation without database queries.
        Uses PermissionBound for permission checks and serializer validation.
        """
        from statezero.adaptors.django.permission_bound import PermissionBound
        from statezero.adaptors.django.permission_resolver import PermissionResolver

        resolver = PermissionResolver(request, registry, self)
        bound = PermissionBound(model, request, resolver, self, serializer, depth=0)

        operation_type = "create" if validate_type == "create" else "update"
        allowed_fields = bound.permitted_fields(model, operation_type)
        if not allowed_fields:
            raise PermissionDenied(f"{validate_type.title()} not allowed")

        # Filter data to only allowed fields
        filtered_data = {k: v for k, v in data.items() if k in allowed_fields}

        # Create minimal fields map for serializer
        model_name = self.get_model_name(model)
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
