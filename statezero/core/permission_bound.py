from collections import deque
from typing import Any, Dict, Optional, Set, Type

from statezero.core.exceptions import PermissionDenied
from statezero.core.interfaces import AbstractDataSerializer, AbstractORMProvider
from statezero.core.permission_resolver import PermissionResolver
from statezero.core.types import ActionType


# ---------------------------------------------------------------------------
# Fields-map builder (BFS over the model graph, uses resolver for permissions)
# ---------------------------------------------------------------------------

def _build_fields_map(resolver, orm_provider, model, operation_type="read", depth=1):
    """
    BFS over the model graph up to *depth*, collecting permitted fields per
    model.  Returns ``Dict[str, Set[str]]`` keyed by model name.

    This mirrors ``ASTParser._get_depth_based_fields`` but delegates all
    permission checks to the supplied *resolver*.
    """
    fields_map: Dict[str, Set[str]] = {}
    visited: set = set()
    model_graph = orm_provider.build_model_graph(model)

    queue = deque([(model, 0)])

    while queue:
        current_model, current_depth = queue.popleft()
        model_name = orm_provider.get_model_name(current_model)

        if (model_name, current_depth) in visited:
            continue
        visited.add((model_name, current_depth))

        if not resolver.has_permission(current_model, operation_type):
            continue

        allowed_fields = resolver.get_fields(current_model, operation_type)
        fields_map.setdefault(model_name, set())

        for node in model_graph.successors(model_name):
            field_data = model_graph.nodes[node].get("data")
            if field_data and field_data.field_name in allowed_fields:
                fields_map[model_name].add(field_data.field_name)

        if current_depth >= depth:
            continue

        for node in model_graph.successors(model_name):
            field_data = model_graph.nodes[node].get("data")
            if (
                field_data
                and field_data.is_relation
                and field_data.related_model
                and field_data.field_name in allowed_fields
            ):
                related_model = orm_provider.get_model_by_name(field_data.related_model)
                queue.append((related_model, current_depth + 1))

    return fields_map


class SyntheticRequest:
    """Minimal request-like object that carries a ``.user`` attribute."""

    def __init__(self, user):
        self.user = user
        self.parser_context = {}


class PermissionBound:
    """
    Permission-scoped model access API (ORM-agnostic core).

    Requires ``registry``, ``orm_provider``, and ``serializer`` to be
    provided explicitly.  For Django convenience defaults see
    ``statezero.adaptors.django.permission_bound.DjangoPermissionBound``.
    """

    def __init__(
        self,
        model: Type,
        user,
        registry,
        orm_provider: AbstractORMProvider,
        serializer: AbstractDataSerializer,
        depth: int = 1,
    ):
        # Accept either a raw User or a framework Request
        if hasattr(user, "user"):
            request = user
        else:
            request = SyntheticRequest(user)

        self.model = model
        self.request = request
        self.registry = registry
        self.orm_provider = orm_provider
        self.serializer = serializer
        self.depth = depth

        self.resolver = PermissionResolver(
            request=request,
            registry=registry,
            orm_provider=orm_provider,
        )

        # Eagerly resolve common permission data
        self.allowed_actions = self.resolver.allowed_actions(model)
        self.read_fields = self.resolver.get_fields(model, "read")
        self.create_fields = self.resolver.get_fields(model, "create")
        self.update_fields = self.resolver.get_fields(model, "update")

        # Build the recursive fields map (model_name -> field set) for read
        self.read_fields_map = _build_fields_map(
            self.resolver, orm_provider, model, "read", depth=depth,
        )

        # Build permission-scoped base queryset
        raw_qs = self.orm_provider.get_queryset(
            request=request,
            model=model,
            initial_ast={},
            registered_permissions=self.registry.get_config(model).permissions,
        )
        self.base_queryset = self.resolver.apply_queryset_permissions(model, raw_qs)

    @property
    def objects(self):
        """Return a :class:`PermissionBoundQuerySet` over the scoped queryset."""
        return PermissionBoundQuerySet(self.base_queryset, self)


# ---------------------------------------------------------------------------
# PermissionBoundQuerySet
# ---------------------------------------------------------------------------

# Chainable methods that return a new queryset
_CHAINABLE = frozenset(
    {
        "filter",
        "exclude",
        "order_by",
        "select_related",
        "prefetch_related",
        "all",
        "none",
        "only",
        "defer",
        "distinct",
    }
)


class PermissionBoundQuerySet:
    """
    Thin wrapper around a QuerySet that enforces permissions on
    every CRUD operation and yields :class:`PermissionBoundInstance` objects.
    """

    def __init__(self, queryset, bound: PermissionBound):
        self._qs = queryset
        self._bound = bound

    # -- Chainable proxies ---------------------------------------------------

    def __getattr__(self, name):
        if name in _CHAINABLE:
            def _chain(*args, **kwargs):
                new_qs = getattr(self._qs, name)(*args, **kwargs)
                return PermissionBoundQuerySet(new_qs, self._bound)
            return _chain
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __getitem__(self, key):
        result = self._qs[key]
        # Slicing returns a queryset; indexing returns an instance
        if hasattr(result, "filter"):
            return PermissionBoundQuerySet(result, self._bound)
        return _wrap_instance(result, self._bound)

    # -- Terminal methods ----------------------------------------------------

    def first(self):
        obj = self._qs.first()
        return _wrap_instance(obj, self._bound) if obj is not None else None

    def last(self):
        obj = self._qs.last()
        return _wrap_instance(obj, self._bound) if obj is not None else None

    def get(self, *args, **kwargs):
        obj = self._qs.get(*args, **kwargs)
        return _wrap_instance(obj, self._bound)

    def exists(self):
        return self._qs.exists()

    def count(self):
        return self._qs.count()

    def aggregate(self, *args, **kwargs):
        return self._qs.aggregate(*args, **kwargs)

    def values(self, *args, **kwargs):
        return self._qs.values(*args, **kwargs)

    def values_list(self, *args, **kwargs):
        return self._qs.values_list(*args, **kwargs)

    # -- Iteration -----------------------------------------------------------

    def __iter__(self):
        for obj in self._qs:
            yield _wrap_instance(obj, self._bound)

    def __len__(self):
        return len(self._qs)

    def __bool__(self):
        return self._qs.exists()

    def __repr__(self):
        return f"<PermissionBoundQuerySet model={self._bound.model.__name__}>"

    # -- Serialization -------------------------------------------------------

    def serialize(self, many=True):
        """
        Optimize and serialize the queryset using the permission-scoped
        fields map.  Returns the same format as the HTTP response path.

        Optimization (select_related / prefetch_related) is handled
        internally by the serializer implementation.
        """
        return self._bound.serializer.serialize(
            data=self._qs,
            model=self._bound.model,
            depth=self._bound.depth,
            fields_map=self._bound.read_fields_map,
            many=many,
        )

    # -- CRUD ----------------------------------------------------------------

    def create(self, **kwargs):
        self._check_action(ActionType.CREATE)
        filtered = self._bound.resolver.filter_writable_data(
            self._bound.model, kwargs, create=True
        )
        obj = self._qs.model.objects.create(**filtered)
        return _wrap_instance(obj, self._bound)

    def bulk_create(self, objs, **kwargs):
        self._check_action(ActionType.CREATE)
        create_fields = self._bound.create_fields
        cleaned = []
        for obj in objs:
            if isinstance(obj, dict):
                cleaned.append(
                    self._qs.model(**{k: v for k, v in obj.items() if k in create_fields})
                )
            else:
                cleaned.append(obj)
        result = self._qs.model.objects.bulk_create(cleaned, **kwargs)
        return [_wrap_instance(o, self._bound) for o in result]

    def update(self, **kwargs):
        self._check_action(ActionType.UPDATE)
        filtered = self._bound.resolver.filter_writable_data(
            self._bound.model, kwargs, create=False
        )
        return self._qs.update(**filtered)

    def delete(self):
        self._check_action(ActionType.DELETE)
        return self._qs.delete()

    def get_or_create(self, defaults=None, **kwargs):
        self._check_action(ActionType.READ)
        defaults = defaults or {}
        filtered_defaults = self._bound.resolver.filter_writable_data(
            self._bound.model, defaults, create=True
        )
        obj, created = self._qs.get_or_create(defaults=filtered_defaults, **kwargs)
        return _wrap_instance(obj, self._bound), created

    def update_or_create(self, defaults=None, **kwargs):
        self._check_action(ActionType.UPDATE)
        defaults = defaults or {}
        filtered_defaults = self._bound.resolver.filter_writable_data(
            self._bound.model, defaults, create=True
        )
        obj, created = self._qs.update_or_create(defaults=filtered_defaults, **kwargs)
        return _wrap_instance(obj, self._bound), created

    # -- Helpers -------------------------------------------------------------

    def _check_action(self, action: ActionType):
        if action not in self._bound.allowed_actions:
            raise PermissionDenied(
                f"{action.value} not allowed on {self._bound.model.__name__}"
            )


# ---------------------------------------------------------------------------
# PermissionBoundInstance
# ---------------------------------------------------------------------------

# Attributes that bypass the permission proxy
_INTERNAL_ATTRS = frozenset(
    {
        "_instance",
        "_read_fields",
        "_update_fields",
        "_allowed_actions",
        "_bound",
        "_pk_field",
    }
)


class PermissionBoundInstance:
    """
    Proxy around a model instance that gates attribute access by
    the resolved read/update field sets.
    """

    __slots__ = (
        "_instance",
        "_read_fields",
        "_update_fields",
        "_allowed_actions",
        "_bound",
        "_pk_field",
    )

    def __init__(
        self,
        instance,
        read_fields: Set[str],
        update_fields: Set[str],
        allowed_actions: Set[ActionType],
        bound: PermissionBound,
    ):
        object.__setattr__(self, "_instance", instance)
        object.__setattr__(self, "_read_fields", read_fields)
        object.__setattr__(self, "_update_fields", update_fields)
        object.__setattr__(self, "_allowed_actions", allowed_actions)
        object.__setattr__(self, "_bound", bound)
        object.__setattr__(self, "_pk_field", instance._meta.pk.name if instance else "pk")

    # -- Read access ---------------------------------------------------------

    def __getattr__(self, name):
        # pk is always readable
        if name == "pk" or name == self._pk_field:
            return getattr(self._instance, name)
        if name in self._read_fields:
            return getattr(self._instance, name)
        raise PermissionDenied(
            f"Field '{name}' is not readable on {type(self._instance).__name__}"
        )

    # -- Write access --------------------------------------------------------

    def __setattr__(self, name, value):
        if name in _INTERNAL_ATTRS:
            object.__setattr__(self, name, value)
            return
        if name == "pk" or name == self._pk_field:
            setattr(self._instance, name, value)
            return
        if name in self._update_fields:
            setattr(self._instance, name, value)
            return
        raise PermissionDenied(
            f"Field '{name}' is not writable on {type(self._instance).__name__}"
        )

    # -- Operations ----------------------------------------------------------

    def save(self, **kwargs):
        if ActionType.UPDATE not in self._allowed_actions:
            raise PermissionDenied(
                f"UPDATE not allowed on {type(self._instance).__name__}"
            )
        self._instance.save(**kwargs)

    def delete(self, **kwargs):
        if ActionType.DELETE not in self._allowed_actions:
            raise PermissionDenied(
                f"DELETE not allowed on {type(self._instance).__name__}"
            )
        # Object-level permission check
        model_config = self._bound.registry.get_config(self._bound.model)
        for permission_cls in model_config.permissions:
            perm = permission_cls()
            obj_actions = perm.allowed_object_actions(
                self._bound.request, self._instance, self._bound.model
            )
            if ActionType.DELETE not in obj_actions:
                raise PermissionDenied(
                    f"Object-level DELETE not allowed on {type(self._instance).__name__}"
                )
        return self._instance.delete(**kwargs)

    def serialize(self):
        """Serialize this single instance using the permission-scoped fields map."""
        return self._bound.serializer.serialize(
            data=self._instance,
            model=type(self._instance),
            depth=self._bound.depth,
            fields_map=self._bound.read_fields_map,
            many=False,
        )

    @property
    def _unwrap(self):
        """Escape hatch: return the raw model instance."""
        return self._instance

    def __repr__(self):
        return f"<PermissionBoundInstance: {self._instance!r}>"

    def __str__(self):
        return str(self._instance)

    def __eq__(self, other):
        if isinstance(other, PermissionBoundInstance):
            return self._instance == other._instance
        return self._instance == other

    def __hash__(self):
        return hash(self._instance)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap_instance(obj, bound: PermissionBound) -> PermissionBoundInstance:
    return PermissionBoundInstance(
        instance=obj,
        read_fields=bound.read_fields,
        update_fields=bound.update_fields,
        allowed_actions=bound.allowed_actions,
        bound=bound,
    )
