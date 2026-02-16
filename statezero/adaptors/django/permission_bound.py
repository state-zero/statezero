"""
Queryset-style API with embedded permission enforcement.

Usage:
    from statezero.adaptors.django.permission_bound import for_user

    bound = for_user(MyModel, request)
    bound.objects.filter(active=True).first()   # returns PermissionBoundInstance
    bound.objects.create(name="x")              # checks CREATE permission
"""
from collections import deque
from typing import Any, Dict, Optional, Set, Type

from django.db.models.fields.related import ForeignObjectRel

from statezero.core.exceptions import PermissionDenied
from statezero.core.types import ActionType


class SyntheticRequest:
    """Minimal request wrapper when only a User object is passed."""

    def __init__(self, user):
        self.user = user


def for_user(model: Type, request_or_user: Any, depth: int = 1):
    """Entry point: returns a PermissionBound for the model scoped to the user."""
    from statezero.adaptors.django.config import config, registry
    from statezero.adaptors.django.permission_resolver import PermissionResolver

    if hasattr(request_or_user, "user"):
        request = request_or_user
    else:
        request = SyntheticRequest(request_or_user)

    resolver = PermissionResolver(request, registry, config.orm_provider)
    return PermissionBound(
        model=model,
        request=request,
        resolver=resolver,
        orm_provider=config.orm_provider,
        serializer=config.serializer,
        depth=depth,
    )


class PermissionBound:
    """Holds resolved permission state for a model + request pair."""

    def __init__(
        self,
        model: Type,
        request: Any,
        resolver,
        orm_provider,
        serializer,
        depth: int = 1,
    ):
        self.model = model
        self.request = request
        self.resolver = resolver
        self.orm_provider = orm_provider
        self.serializer = serializer
        self.depth = depth

        self.allowed_actions = resolver.allowed_actions(model)
        self.read_fields = resolver.permitted_fields(model, "read")
        self.update_fields = resolver.permitted_fields(model, "update")
        self.create_fields = resolver.permitted_fields(model, "create")

        # Build nested fields maps for serialization/deserialization
        self.read_fields_map = self._build_fields_map(depth, "read")
        self.create_fields_map = self._build_fields_map(0, "create")
        self.update_fields_map = self._build_fields_map(0, "update")

        # Apply queryset-level permissions
        raw_qs = model.objects.all()
        self.base_queryset = resolver.apply_queryset_permissions(model, raw_qs)

    def permitted_fields(self, model, operation_type):
        """Resolve permitted fields for any model (used by ASTParser for nested field validation)."""
        return self.resolver.permitted_fields(model, operation_type)

    @property
    def objects(self):
        """Return a PermissionBoundQuerySet wrapping the base queryset."""
        return PermissionBoundQuerySet(
            queryset=self.base_queryset,
            bound=self,
        )

    # ------------------------------------------------------------------
    # Fields-map builder (adapted from ast_parser._expand_fields_to_depth)
    # ------------------------------------------------------------------

    def _build_fields_map(
        self, depth: int, operation_type: str
    ) -> Dict[str, Set[str]]:
        """BFS traversal to build {model_name: {fields}} up to *depth*."""
        from statezero.adaptors.django.config import registry

        fields_map: Dict[str, Set[str]] = {}
        visited: set = set()
        queue = deque([(self.model, 0)])

        while queue:
            current_model, current_depth = queue.popleft()
            model_name = self.orm_provider.get_model_name(current_model)

            if (model_name, current_depth) in visited:
                continue
            visited.add((model_name, current_depth))

            allowed_fields = self.resolver.permitted_fields(current_model, operation_type)
            if not allowed_fields:
                continue

            fields_map.setdefault(model_name, set())

            try:
                model_config = registry.get_config(current_model)
                configured_fields = model_config.fields
            except (ValueError, KeyError):
                configured_fields = "__all__"

            for field in current_model._meta.get_fields():
                field_name = field.name
                if isinstance(field, ForeignObjectRel):
                    if configured_fields == "__all__" or field_name not in configured_fields:
                        continue
                if field_name in allowed_fields:
                    fields_map[model_name].add(field_name)

            # Additional (computed) fields
            try:
                for af in registry.get_config(current_model).additional_fields:
                    if af.name in allowed_fields:
                        fields_map[model_name].add(af.name)
            except (ValueError, KeyError):
                pass

            if current_depth >= depth:
                continue

            # Traverse relations
            for field in current_model._meta.get_fields():
                field_name = field.name
                if isinstance(field, ForeignObjectRel):
                    if configured_fields == "__all__" or field_name not in configured_fields:
                        continue
                    if field_name in allowed_fields and getattr(field, "related_model", None):
                        queue.append((field.related_model, current_depth + 1))
                    continue
                if field.is_relation and getattr(field, "related_model", None):
                    if field_name in allowed_fields:
                        queue.append((field.related_model, current_depth + 1))

        return fields_map


class PermissionBoundQuerySet:
    """Thin wrapper around a Django QuerySet with embedded permission checks."""

    def __init__(self, queryset, bound: PermissionBound):
        self._qs = queryset
        self._bound = bound

    # ------------------------------------------------------------------
    # Chainable proxies
    # ------------------------------------------------------------------

    def _wrap(self, new_qs):
        return PermissionBoundQuerySet(new_qs, self._bound)

    def filter(self, *args, **kwargs):
        return self._wrap(self._qs.filter(*args, **kwargs))

    def exclude(self, *args, **kwargs):
        return self._wrap(self._qs.exclude(*args, **kwargs))

    def order_by(self, *args):
        return self._wrap(self._qs.order_by(*args))

    def select_related(self, *args):
        return self._wrap(self._qs.select_related(*args))

    def prefetch_related(self, *args):
        return self._wrap(self._qs.prefetch_related(*args))

    def all(self):
        return self._wrap(self._qs.all())

    def none(self):
        return self._wrap(self._qs.none())

    def only(self, *args):
        return self._wrap(self._qs.only(*args))

    def defer(self, *args):
        return self._wrap(self._qs.defer(*args))

    def distinct(self, *args):
        return self._wrap(self._qs.distinct(*args))

    def count(self):
        return self._qs.count()

    def exists(self):
        return self._qs.exists()

    # ------------------------------------------------------------------
    # Terminal methods with object permissions
    # ------------------------------------------------------------------

    def _wrap_instance(self, obj):
        if obj is None:
            return None
        self._bound.resolver.check_object_permissions(obj, ActionType.READ, self._bound.model)
        return PermissionBoundInstance(obj, self._bound)

    def get(self, *args, **kwargs):
        obj = self._qs.get(*args, **kwargs)
        return self._wrap_instance(obj)

    def first(self):
        obj = self._qs.first()
        return self._wrap_instance(obj)

    def last(self):
        obj = self._qs.last()
        return self._wrap_instance(obj)

    def __iter__(self):
        for obj in self._qs:
            yield PermissionBoundInstance(obj, self._bound)

    def __len__(self):
        return len(self._qs)

    def __bool__(self):
        return self._qs.exists()

    # ------------------------------------------------------------------
    # CRUD with permission enforcement
    # ------------------------------------------------------------------

    def _require_action(self, action: ActionType):
        if action not in self._bound.allowed_actions:
            raise PermissionDenied(
                f"{action.value} action is not permitted on {self._bound.model.__name__}"
            )

    def create(self, **kwargs):
        self._require_action(ActionType.CREATE)
        filtered = {k: v for k, v in kwargs.items() if k in self._bound.create_fields}
        obj = self._bound.model.objects.create(**filtered)
        return PermissionBoundInstance(obj, self._bound)

    def update(self, **kwargs):
        self._require_action(ActionType.UPDATE)
        self._bound.resolver.check_bulk_permissions(self._qs, ActionType.UPDATE, self._bound.model)
        filtered = {k: v for k, v in kwargs.items() if k in self._bound.update_fields}
        return self._qs.update(**filtered)

    def delete(self):
        self._require_action(ActionType.DELETE)
        self._bound.resolver.check_bulk_permissions(self._qs, ActionType.DELETE, self._bound.model)
        return self._qs.delete()

    def get_or_create(self, defaults=None, **kwargs):
        self._require_action(ActionType.READ)
        defaults = defaults or {}
        try:
            obj = self._qs.get(**kwargs)
            created = False
            self._bound.resolver.check_object_permissions(obj, ActionType.READ, self._bound.model)
        except self._bound.model.DoesNotExist:
            self._require_action(ActionType.CREATE)
            filtered_defaults = {k: v for k, v in defaults.items() if k in self._bound.create_fields}
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in self._bound.create_fields}
            obj = self._bound.model.objects.create(**filtered_kwargs, **filtered_defaults)
            created = True
        return PermissionBoundInstance(obj, self._bound), created

    def update_or_create(self, defaults=None, **kwargs):
        self._require_action(ActionType.UPDATE)
        defaults = defaults or {}
        try:
            obj = self._qs.get(**kwargs)
            self._bound.resolver.check_object_permissions(obj, ActionType.UPDATE, self._bound.model)
            filtered_defaults = {k: v for k, v in defaults.items() if k in self._bound.update_fields}
            for k, v in filtered_defaults.items():
                setattr(obj, k, v)
            obj.save()
            created = False
        except self._bound.model.DoesNotExist:
            self._require_action(ActionType.CREATE)
            filtered_defaults = {k: v for k, v in defaults.items() if k in self._bound.create_fields}
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in self._bound.create_fields}
            obj = self._bound.model.objects.create(**filtered_kwargs, **filtered_defaults)
            created = True
        return PermissionBoundInstance(obj, self._bound), created

    def bulk_create(self, objs):
        self._require_action(ActionType.CREATE)
        create_fields = self._bound.create_fields
        cleaned = []
        for obj in objs:
            # Filter obj's fields to only allowed create fields
            instance = self._bound.model()
            for field_name in create_fields:
                if hasattr(obj, field_name):
                    setattr(instance, field_name, getattr(obj, field_name))
            cleaned.append(instance)
        created = self._bound.model.objects.bulk_create(cleaned)
        return [PermissionBoundInstance(o, self._bound) for o in created]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def serialize(self, many=True):
        return self._bound.serializer.serialize(
            data=self._qs,
            model=self._bound.model,
            many=many,
            depth=self._bound.depth,
            fields_map=self._bound.read_fields_map,
        )


class PermissionBoundInstance:
    """Proxy around a model instance with field-level permission gating."""

    # Attributes that belong to the proxy itself (not forwarded to the instance)
    _PROXY_ATTRS = frozenset({
        "_instance", "_bound", "_PROXY_ATTRS",
    })

    def __init__(self, instance, bound: PermissionBound):
        # Bypass __setattr__ for proxy attrs
        object.__setattr__(self, "_instance", instance)
        object.__setattr__(self, "_bound", bound)

    @property
    def pk(self):
        return self._instance.pk

    @property
    def _unwrap(self):
        """Escape hatch — return the raw model instance."""
        return self._instance

    def __getattr__(self, name):
        if name == "pk":
            return self._instance.pk
        if name in self._bound.read_fields:
            return getattr(self._instance, name)
        raise PermissionDenied(
            f"Read access to field '{name}' on {self._bound.model.__name__} is not permitted"
        )

    def __setattr__(self, name, value):
        if name in self._PROXY_ATTRS:
            object.__setattr__(self, name, value)
            return
        if name == "pk":
            setattr(self._instance, name, value)
            return
        if name in self._bound.update_fields:
            setattr(self._instance, name, value)
            return
        raise PermissionDenied(
            f"Write access to field '{name}' on {self._bound.model.__name__} is not permitted"
        )

    def save(self, **kwargs):
        self._require_action(ActionType.UPDATE)
        self._bound.resolver.check_object_permissions(
            self._instance, ActionType.UPDATE, self._bound.model,
        )
        self._instance.save(**kwargs)

    def delete(self, **kwargs):
        self._require_action(ActionType.DELETE)
        self._bound.resolver.check_object_permissions(
            self._instance, ActionType.DELETE, self._bound.model,
        )
        return self._instance.delete(**kwargs)

    def serialize(self):
        return self._bound.serializer.serialize(
            data=self._instance,
            model=self._bound.model,
            many=False,
            depth=self._bound.depth,
            fields_map=self._bound.read_fields_map,
        )

    def _require_action(self, action: ActionType):
        if action not in self._bound.allowed_actions:
            raise PermissionDenied(
                f"{action.value} action is not permitted on {self._bound.model.__name__}"
            )

    def __repr__(self):
        return f"<PermissionBoundInstance: {self._instance!r}>"

    def __str__(self):
        return str(self._instance)
