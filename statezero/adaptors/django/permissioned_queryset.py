from __future__ import annotations

from typing import Any, Optional, Set, Tuple, Type, Union

from django.db import models
from django.db.models import Q, QuerySet
from django.db.models.expressions import Col, F
from django.db.models.fields.related import ForeignObjectRel

from statezero.core.exceptions import PermissionDenied, ValidationError
from statezero.core.types import ActionType

# Lookup operators and date/time transforms that are NOT field names.
# Mirrors _FILTER_MODIFIERS in ast_parser.py.
_FILTER_MODIFIERS = {
    "contains", "icontains", "startswith", "istartswith",
    "endswith", "iendswith", "lt", "gt", "lte", "gte",
    "in", "eq", "exact", "iexact", "isnull", "range",
    "regex", "iregex",
    "year", "month", "day", "hour", "minute", "second",
    "week", "week_day", "iso_week_day", "quarter",
    "iso_year", "date", "time",
}


class _FakeRequest:
    """Minimal request-like wrapper so permissions can access request.user."""

    def __init__(self, user):
        self.user = user


class _PermissionedInstance:
    """
    Lightweight proxy around a Django model instance that intercepts attribute
    access for additional (computed) fields the user may not read, and enforces
    action permissions on ``.save()`` and ``.delete()``.

    When a ``PermissionedQuerySet`` has determined that the current user lacks
    visibility on certain additional fields, instances yielded by iteration are
    wrapped in this proxy so that accessing a hidden field raises
    ``PermissionDenied`` instead of silently returning the value.
    """

    __slots__ = ("_pi_wrapped", "_pi_hidden", "_pi_pqs")

    def __init__(self, instance, hidden_fields: frozenset, pqs=None):
        object.__setattr__(self, "_pi_wrapped", instance)
        object.__setattr__(self, "_pi_hidden", hidden_fields)
        object.__setattr__(self, "_pi_pqs", pqs)

    def __getattr__(self, name):
        if name in object.__getattribute__(self, "_pi_hidden"):
            raise PermissionDenied(
                f"Permission denied: you do not have access to "
                f"read field '{name}'"
            )
        return getattr(object.__getattribute__(self, "_pi_wrapped"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_pi_wrapped"), name, value)

    @property
    def __class__(self):
        return object.__getattribute__(self, "_pi_wrapped").__class__

    def __repr__(self):
        return repr(object.__getattribute__(self, "_pi_wrapped"))

    def __str__(self):
        return str(object.__getattribute__(self, "_pi_wrapped"))

    def __eq__(self, other):
        wrapped = object.__getattribute__(self, "_pi_wrapped")
        if isinstance(other, _PermissionedInstance):
            return wrapped == object.__getattribute__(other, "_pi_wrapped")
        return wrapped == other

    def __hash__(self):
        return hash(object.__getattribute__(self, "_pi_wrapped"))

    def save(self, *args, **kwargs):
        pqs = object.__getattribute__(self, "_pi_pqs")
        wrapped = object.__getattribute__(self, "_pi_wrapped")
        if pqs is not None:
            pqs._check_action(ActionType.UPDATE)
            pqs._check_object_permission(wrapped, ActionType.UPDATE)
        return wrapped.save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pqs = object.__getattribute__(self, "_pi_pqs")
        wrapped = object.__getattribute__(self, "_pi_wrapped")
        if pqs is not None:
            pqs._check_action(ActionType.DELETE)
            pqs._check_object_permission(wrapped, ActionType.DELETE)
        return wrapped.delete(*args, **kwargs)

    @property
    def _wrapped(self):
        """Access the underlying model instance."""
        return object.__getattribute__(self, "_pi_wrapped")


class PermissionedQuerySet(QuerySet):
    """
    A Django QuerySet that encapsulates all StateZero permissions for a user.

    Created via ``for_user(Model, user)`` or ``Model.for_user(user)`` (if
    installed).  Once created, this object behaves identically to a regular
    QuerySet for reads – filter / exclude / order_by / count / exists / iterate
    all work as expected – but the result set is already scoped to only the rows
    the user is permitted to see, and write operations (create / update / delete)
    enforce operation-level, field-level, object-level, and bulk permissions
    automatically.

    Permissions enforced
    --------------------
    * **Row-level** – ``filter_queryset`` (OR across permission classes) and
      ``exclude_from_queryset`` (AND) are applied when the queryset is created.
    * **Operation-level** – ``allowed_actions`` is checked before any write.
    * **Field-level** – write data is filtered to only permitted fields.
    * **Object-level** – ``allowed_object_actions`` checked per-instance for
      small querysets; ``bulk_operation_allowed`` for larger ones.

    Exposed metadata
    ----------------
    * ``allowed_actions``  – ``Set[ActionType]``
    * ``visible_fields``   – ``Set[str]``
    * ``editable_fields``  – ``Set[str]``
    * ``create_fields``    – ``Set[str]``
    """

    def __init__(self, model=None, query=None, using=None, hints=None):
        super().__init__(model, query, using, hints)
        self._sz_request = None
        self._sz_model_config = None
        self._sz_allowed_actions: Optional[Set[ActionType]] = None
        self._sz_visible_fields: Optional[Set[str]] = None
        self._sz_editable_fields: Optional[Set[str]] = None
        self._sz_create_fields: Optional[Set[str]] = None
        self._sz_all_fields: Optional[Set[str]] = None
        self._sz_permissions_resolved: bool = False
        self._sz_additional_field_names: frozenset = frozenset()

    # ------------------------------------------------------------------
    # Clone support – Django creates clones on every chaining call
    # ------------------------------------------------------------------

    def _clone(self):
        c = super()._clone()
        c._sz_request = self._sz_request
        c._sz_model_config = self._sz_model_config
        c._sz_allowed_actions = self._sz_allowed_actions
        c._sz_visible_fields = self._sz_visible_fields
        c._sz_editable_fields = self._sz_editable_fields
        c._sz_create_fields = self._sz_create_fields
        c._sz_all_fields = self._sz_all_fields
        c._sz_permissions_resolved = self._sz_permissions_resolved
        c._sz_additional_field_names = self._sz_additional_field_names
        return c

    # ------------------------------------------------------------------
    # Permission metadata (read-only properties)
    # ------------------------------------------------------------------

    @property
    def allowed_actions(self) -> Set[ActionType]:
        self._ensure_resolved()
        return set(self._sz_allowed_actions)

    @property
    def visible_fields(self) -> Set[str]:
        self._ensure_resolved()
        return set(self._sz_visible_fields)

    @property
    def editable_fields(self) -> Set[str]:
        self._ensure_resolved()
        return set(self._sz_editable_fields)

    @property
    def create_fields(self) -> Set[str]:
        self._ensure_resolved()
        return set(self._sz_create_fields)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def can(self, action: ActionType) -> bool:
        """Return True if *action* is permitted (does not raise)."""
        self._ensure_resolved()
        return action in self._sz_allowed_actions

    def can_read(self, field_name: str) -> bool:
        self._ensure_resolved()
        return field_name in self._sz_visible_fields

    def can_edit(self, field_name: str) -> bool:
        self._ensure_resolved()
        return field_name in self._sz_editable_fields

    # ------------------------------------------------------------------
    # Filter / exclude overrides – validate field-level read permissions
    # ------------------------------------------------------------------

    def filter(self, *args, **kwargs):
        if self._sz_permissions_resolved:
            self._validate_filter_args(args, kwargs)
        return super().filter(*args, **kwargs)

    def exclude(self, *args, **kwargs):
        if self._sz_permissions_resolved:
            self._validate_filter_args(args, kwargs)
        return super().exclude(*args, **kwargs)

    # ------------------------------------------------------------------
    # values / values_list – validate field-level read permissions
    # ------------------------------------------------------------------

    def values(self, *fields, **expressions):
        if self._sz_permissions_resolved:
            if fields:
                self._validate_value_fields(fields)
            else:
                # No args — restrict to visible DB fields + pk only
                fields = self._visible_db_fields()
        return super().values(*fields, **expressions)

    def values_list(self, *fields, **kwargs):
        if self._sz_permissions_resolved:
            if fields:
                self._validate_value_fields(fields)
            else:
                # No args — restrict to visible DB fields + pk only
                fields = self._visible_db_fields()
        return super().values_list(*fields, **kwargs)

    def _visible_db_fields(self):
        """Return a tuple of visible fields that exist as DB columns."""
        db_field_names = {f.name for f in self.model._meta.get_fields() if hasattr(f, 'column')}
        pk_name = self.model._meta.pk.name
        return tuple(
            f for f in self._sz_visible_fields
            if f in db_field_names or f == pk_name
        )

    def _validate_value_fields(self, fields):
        for field_name in fields:
            if field_name == "pk" or field_name == self.model._meta.pk.name:
                continue
            if field_name not in self._sz_visible_fields:
                if not (field_name.endswith("_id") and field_name[:-3] in self._sz_visible_fields):
                    raise PermissionDenied(
                        f"Permission denied: you do not have access to "
                        f"read field '{field_name}'"
                    )

    # ------------------------------------------------------------------
    # annotate – validate F expressions for field-level read permissions
    # ------------------------------------------------------------------

    def annotate(self, *args, **kwargs):
        if self._sz_permissions_resolved:
            for expr in args:
                self._validate_expression(expr)
            for expr in kwargs.values():
                self._validate_expression(expr)
        return super().annotate(*args, **kwargs)

    def _validate_expression(self, expr):
        """Recursively inspect an expression tree for hidden field references."""
        if isinstance(expr, F):
            field_name = expr.name.split("__")[0]
            if field_name != "pk" and field_name != self.model._meta.pk.name:
                if field_name not in self._sz_visible_fields:
                    if not (field_name.endswith("_id") and field_name[:-3] in self._sz_visible_fields):
                        raise PermissionDenied(
                            f"Permission denied: you do not have access to "
                            f"read field '{field_name}'"
                        )
        if hasattr(expr, "get_source_expressions"):
            for sub in expr.get_source_expressions():
                if sub is not None:
                    self._validate_expression(sub)

    # ------------------------------------------------------------------
    # aggregate – validate field references in aggregate expressions
    # ------------------------------------------------------------------

    def aggregate(self, *args, **kwargs):
        if self._sz_permissions_resolved:
            for expr in args:
                self._validate_expression(expr)
            for expr in kwargs.values():
                self._validate_expression(expr)
        return super().aggregate(*args, **kwargs)

    # ------------------------------------------------------------------
    # order_by – validate field-level read permissions
    # ------------------------------------------------------------------

    def order_by(self, *field_names):
        if self._sz_permissions_resolved:
            for field_name in field_names:
                if isinstance(field_name, str):
                    clean = field_name.lstrip("-")
                    if clean == "pk" or clean == self.model._meta.pk.name:
                        continue
                    if not self._field_exists_on_model(self.model, clean):
                        raise ValidationError(
                            f"Cannot order by '{field_name}': field does not "
                            f"exist on model {self.model.__name__}."
                        )
                    if clean not in self._sz_visible_fields:
                        if not (clean.endswith("_id") and clean[:-3] in self._sz_visible_fields):
                            raise PermissionDenied(
                                f"Permission denied: you do not have access to "
                                f"order by field '{field_name}'"
                            )
        return super().order_by(*field_names)

    # ------------------------------------------------------------------
    # Iteration – wrap instances to enforce additional-field permissions
    # ------------------------------------------------------------------

    def __iter__(self):
        for instance in super().__iter__():
            yield self._wrap_instance(instance)

    def iterator(self, chunk_size=None):
        kwargs = {}
        if chunk_size is not None:
            kwargs["chunk_size"] = chunk_size
        for instance in super().iterator(**kwargs):
            yield self._wrap_instance(instance)

    def get(self, *args, **kwargs):
        """Override to wrap the returned instance for additional-field enforcement."""
        obj = super().get(*args, **kwargs)
        return self._wrap_instance(obj)

    def _wrap_instance(self, instance):
        # Only wrap actual model instances, not dicts/tuples from values()/values_list()
        if not isinstance(instance, models.Model):
            return instance
        hidden = self._sz_all_fields - self._sz_visible_fields
        if self._sz_additional_field_names:
            hidden |= self._sz_additional_field_names - self._sz_visible_fields
        # PK must always be accessible (serializers need it)
        hidden.discard(self.model._meta.pk.name)
        # Always wrap to enforce action permissions on save/delete
        return _PermissionedInstance(instance, hidden, self)

    # ------------------------------------------------------------------
    # Write-operation overrides
    # ------------------------------------------------------------------

    def create(self, **kwargs):
        self._ensure_resolved()
        self._check_action(ActionType.CREATE)
        kwargs = self._filter_write_data(kwargs, self._sz_create_fields)
        return super().create(**kwargs)

    def bulk_create(self, objs, *args, **kwargs):
        self._ensure_resolved()
        self._check_action(ActionType.BULK_CREATE)
        objs = self._strip_hidden_fields_from_instances(objs, self._sz_create_fields)
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        self._ensure_resolved()
        self._check_action(ActionType.UPDATE)
        self._check_bulk_permission(self, ActionType.UPDATE)
        # Validate F expressions in values before filtering keys
        for v in kwargs.values():
            if isinstance(v, F) or hasattr(v, "get_source_expressions"):
                self._validate_expression(v)
        kwargs = self._filter_write_data(kwargs, self._sz_editable_fields)
        if not kwargs:
            return 0
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, *args, **kwargs):
        self._ensure_resolved()
        self._check_action(ActionType.UPDATE)
        # Filter field list to only editable fields
        fields = [f for f in fields if f in self._sz_editable_fields
                  or (f.endswith("_id") and f[:-3] in self._sz_editable_fields)]
        if not fields:
            return 0
        return super().bulk_update(objs, fields, *args, **kwargs)

    def delete(self):
        self._ensure_resolved()
        self._check_action(ActionType.DELETE)
        self._check_bulk_permission(self, ActionType.DELETE)
        return super().delete()

    def get_or_create(self, defaults=None, **kwargs):
        self._ensure_resolved()
        # Validate lookup kwargs against read permissions (filter validation)
        self._validate_filter_args((), kwargs)
        # Try to get the existing object first (read-level operation)
        try:
            obj = self.get(**kwargs)
            return obj, False
        except self.model.DoesNotExist:
            pass
        # Row doesn't exist — need CREATE permission to make a new one
        self._check_action(ActionType.CREATE)
        if defaults:
            defaults = self._filter_write_data(defaults, self._sz_create_fields)
        return super().get_or_create(defaults=defaults, **kwargs)

    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        self._ensure_resolved()
        # Validate lookup kwargs against read permissions (filter validation)
        self._validate_filter_args((), kwargs)
        # Check if the row exists to determine required action
        try:
            self.get(**kwargs)
            # Row exists — need UPDATE permission
            self._check_action(ActionType.UPDATE)
            if defaults:
                defaults = self._filter_write_data(defaults, self._sz_editable_fields)
        except self.model.DoesNotExist:
            # Row doesn't exist — need CREATE permission
            self._check_action(ActionType.CREATE)
            if defaults:
                defaults = self._filter_write_data(defaults, self._sz_create_fields)
        if create_defaults:
            create_defaults = self._filter_write_data(
                create_defaults, self._sz_create_fields
            )
        return super().update_or_create(
            defaults=defaults, create_defaults=create_defaults, **kwargs
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_resolved(self):
        if not self._sz_permissions_resolved:
            raise RuntimeError(
                "PermissionedQuerySet has not been initialised.  "
                "Use for_user(Model, user) to create one."
            )

    def _check_action(self, action: ActionType):
        if action not in self._sz_allowed_actions:
            raise PermissionDenied(
                f"{action.value} is not permitted on {self.model.__name__}"
            )

    def _strip_hidden_fields_from_instances(self, objs, allowed: Set[str]):
        """Reset disallowed fields on model instances to their default values."""
        model_fields = {f.name: f for f in self.model._meta.get_fields() if hasattr(f, 'attname')}
        for obj in objs:
            for field_name, field in model_fields.items():
                if field_name in allowed:
                    continue
                if field_name.endswith("_id") and field_name[:-3] in allowed:
                    continue
                if field_name == self.model._meta.pk.name:
                    continue
                if hasattr(field, 'default') and field.default is not models.fields.NOT_PROVIDED:
                    setattr(obj, field.attname, field.default)
                elif field.null:
                    setattr(obj, field.attname, None)
                elif isinstance(field, models.CharField):
                    setattr(obj, field.attname, "")
        return objs

    @staticmethod
    def _filter_write_data(data: dict, allowed: Set[str]) -> dict:
        result = {}
        for k, v in data.items():
            if k in allowed:
                result[k] = v
            # Django allows fk_field_id as an alias for fk_field in .update()/.create()
            elif k.endswith("_id") and k[:-3] in allowed:
                result[k] = v
        return result

    # ------------------------------------------------------------------
    # Field-path validation for filter / exclude
    # ------------------------------------------------------------------

    def _validate_filter_args(self, args, kwargs):
        """Extract field paths from Q objects and kwargs, then validate each."""
        for key in kwargs:
            self._validate_field_path(key)
        for arg in args:
            if isinstance(arg, Q):
                self._validate_q(arg)

    def _validate_q(self, q: Q):
        """Recursively validate every field path inside a Q tree."""
        for child in q.children:
            if isinstance(child, Q):
                self._validate_q(child)
            elif isinstance(child, tuple) and len(child) == 2:
                self._validate_field_path(child[0])

    def _validate_field_path(self, lookup_key: str):
        """
        Validate that the user has read permission for every model field
        in *lookup_key* (e.g. ``"fk__related_fk__name__icontains"``).

        Mirrors the logic of ``ASTParser.is_field_allowed``.
        """
        from statezero.adaptors.django.config import registry
        from statezero.adaptors.django.permission_utils import resolve_permission_fields

        parts = lookup_key.split("__")
        current_model = self.model
        allowed = self._sz_visible_fields

        for part in parts:
            if part in _FILTER_MODIFIERS:
                break

            if part == "pk" or part == current_model._meta.pk.name:
                break

            # Check if it is a computed/additional field BEFORE permission check
            if part in self._sz_additional_field_names:
                raise ValidationError(
                    f"Cannot filter on computed field '{part}'. "
                    f"Computed fields are not stored in the database."
                )

            # Check field existence before permission check — nonexistent
            # fields should be 400 (ValidationError), not 403 (PermissionDenied)
            if not self._field_exists_on_model(current_model, part):
                raise ValidationError(
                    f"Field '{lookup_key}' does not exist on model "
                    f"{current_model.__name__}."
                )

            # Also accept fk_id when fk is in allowed (Django column alias)
            if part not in allowed:
                if not (part.endswith("_id") and part[:-3] in allowed):
                    raise PermissionDenied(
                        f"Permission denied: you do not have access to "
                        f"filter on field '{lookup_key}'"
                    )

            # Check if it is a JSON field (arbitrary nested paths OK)
            try:
                field_obj = current_model._meta.get_field(part)
                if isinstance(field_obj, models.JSONField):
                    return  # anything after a JSONField is allowed
            except Exception:
                pass

            # If it is a relation, hop to the related model
            is_rel, related = self._resolve_relation(current_model, part)
            if is_rel and related:
                try:
                    rel_config = registry.get_config(related)
                except ValueError:
                    raise PermissionDenied(
                        f"Permission denied: you do not have access to "
                        f"filter on field '{lookup_key}'"
                    )

                if rel_config.fields and rel_config.fields != "__all__":
                    rel_all = set(rel_config.fields)
                else:
                    rel_all = {f.name for f in related._meta.get_fields()}
                    rel_all |= {af.name for af in rel_config.additional_fields}

                allowed = resolve_permission_fields(
                    rel_config, self._sz_request, "read", rel_all
                )
                if not allowed:
                    raise PermissionDenied(
                        f"Permission denied: you do not have access to "
                        f"filter on field '{lookup_key}'"
                    )
                current_model = related
            else:
                break  # non-relation field — stop traversing

    @staticmethod
    def _field_exists_on_model(model: Type[models.Model], field_name: str) -> bool:
        """Return True if *field_name* is a real Django field on *model*."""
        try:
            model._meta.get_field(field_name)
            return True
        except Exception:
            # Also accept fk_id as alias for fk
            if field_name.endswith("_id"):
                try:
                    model._meta.get_field(field_name[:-3])
                    return True
                except Exception:
                    pass
            return False

    @staticmethod
    def _resolve_relation(
        model: Type[models.Model], field_name: str
    ) -> Tuple[bool, Optional[Type[models.Model]]]:
        """Return (is_relation, related_model) for *field_name* on *model*."""
        try:
            field = model._meta.get_field(field_name)
            if isinstance(field, ForeignObjectRel):
                return False, None  # skip reverse relations in filter validation
            if field.is_relation and getattr(field, "related_model", None):
                return True, field.related_model
            return False, None
        except Exception:
            return False, None

    def _check_object_permission(self, obj, action: ActionType):
        allowed_obj_actions: Set[ActionType] = set()
        for perm_cls in self._sz_model_config.permissions:
            perm = perm_cls()
            allowed_obj_actions |= perm.allowed_object_actions(
                self._sz_request, obj, self.model
            )
        if action not in allowed_obj_actions:
            raise PermissionDenied(
                f"Object-level {action.value} denied on {obj}"
            )

    def _check_bulk_permission(self, qs, action: ActionType):
        count = qs.count()
        if count == 0:
            return
        if count <= 1:
            for instance in qs.all():
                self._check_object_permission(instance, action)
        else:
            allowed = False
            for perm_cls in self._sz_model_config.permissions:
                perm = perm_cls()
                if perm.bulk_operation_allowed(
                    self._sz_request, qs, action, self.model
                ):
                    allowed = True
                    break
            if not allowed:
                raise PermissionDenied(
                    f"Bulk {action.value} not permitted on {self.model.__name__}"
                )


# ======================================================================
# Factory function
# ======================================================================


def for_user(
    model: Type[models.Model],
    user_or_request: Any,
) -> PermissionedQuerySet:
    """
    Create a :class:`PermissionedQuerySet` for *model* scoped to
    *user_or_request*.

    Args:
        model: A Django model class registered with StateZero.
        user_or_request: A Django ``User``, ``AnonymousUser``, or a DRF
            ``Request`` object.

    Returns:
        A ``PermissionedQuerySet`` with all permission classes already
        evaluated and the base queryset filtered accordingly.
    """
    from statezero.adaptors.django.config import registry
    from statezero.adaptors.django.permission_utils import (
        resolve_allowed_actions,
        resolve_permission_fields,
    )

    # Normalise to a request-like object.
    if hasattr(user_or_request, "user"):
        request = user_or_request
    else:
        request = _FakeRequest(user_or_request)

    model_config = registry.get_config(model)

    # Resolve all model fields (same logic as DjangoORMAdapter.get_fields).
    if model_config.fields and model_config.fields != "__all__":
        all_fields = set(model_config.fields)
    else:
        all_fields = {f.name for f in model._meta.get_fields()}
        all_fields |= {af.name for af in model_config.additional_fields}

    # Resolve permission metadata.
    allowed_actions = resolve_allowed_actions(model_config, request)
    visible_fields = resolve_permission_fields(
        model_config, request, "read", all_fields
    )
    editable_fields = resolve_permission_fields(
        model_config, request, "update", all_fields
    )
    create_fields = resolve_permission_fields(
        model_config, request, "create", all_fields
    )

    # Always include "repr" in visible_fields (mirrors serializers.py).
    visible_fields.add("repr")

    # Collect additional (computed) field names for read-permission enforcement.
    additional_field_names = frozenset(
        af.name for af in model_config.additional_fields
    )

    # Build the base queryset with row-level permission filtering.
    base_qs = model.objects.all()

    # Step 1 – filter_queryset with OR logic (additive).
    filtered_querysets = []
    for perm_cls in model_config.permissions:
        perm = perm_cls()
        filtered_querysets.append(perm.filter_queryset(request, base_qs))

    if filtered_querysets:
        combined = filtered_querysets[0]
        for qs in filtered_querysets[1:]:
            combined = combined | qs
        base_qs = combined

    # Step 2 – exclude_from_queryset with AND logic (restrictive).
    for perm_cls in model_config.permissions:
        perm = perm_cls()
        base_qs = perm.exclude_from_queryset(request, base_qs)

    # Wrap in a PermissionedQuerySet while keeping the assembled SQL.
    pqs = PermissionedQuerySet(model=model, using=base_qs.db)
    pqs.query = base_qs.query

    pqs._sz_request = request
    pqs._sz_model_config = model_config
    pqs._sz_allowed_actions = allowed_actions
    pqs._sz_visible_fields = visible_fields
    pqs._sz_editable_fields = editable_fields
    pqs._sz_create_fields = create_fields
    pqs._sz_all_fields = all_fields
    pqs._sz_permissions_resolved = True
    pqs._sz_additional_field_names = additional_field_names

    return pqs


# ======================================================================
# Model helpers – install ``for_user`` on model classes
# ======================================================================


class _ForUserDescriptor:
    """
    Descriptor that adds ``Model.for_user(user)`` to a model class.

    Usage::

        class MyModel(models.Model):
            for_user = _ForUserDescriptor()
    """

    def __get__(self, obj, cls):
        if cls is None:
            return self

        def _for_user(user_or_request):
            return for_user(cls, user_or_request)

        return _for_user


def install_for_user(*model_classes: Type[models.Model]) -> None:
    """
    Install ``for_user`` as a class-level callable on each model.

    After calling this, ``Model.for_user(user)`` returns a
    :class:`PermissionedQuerySet`.
    """
    for model in model_classes:
        model.for_user = _ForUserDescriptor()


def install_for_user_on_all_registered_models() -> None:
    """
    Install ``for_user`` on every model currently registered with StateZero.
    """
    from statezero.adaptors.django.config import registry

    install_for_user(*registry._models_config.keys())
