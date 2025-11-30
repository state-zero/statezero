"""
StateZero signals for Django.

This module provides:
1. Signal receivers - Django-style signals for bulk operations
2. Signal triggers - Helper functions for manually triggering events

=============================================================================
RECEIVING SIGNALS
=============================================================================

StateZero provides Django-style signals for bulk operations (since Django
doesn't emit signals for these):

    from django.dispatch import receiver
    from statezero.adaptors.django.signals import (
        post_bulk_create, post_bulk_update, post_bulk_delete
    )

    @receiver(post_bulk_create, sender=MyModel)
    def handle_bulk_create(sender, instances, **kwargs):
        print(f"Created {len(instances)} instances")

    @receiver(post_bulk_update, sender=MyModel)
    def handle_bulk_update(sender, instances, **kwargs):
        print(f"Updated {len(instances)} instances")

    @receiver(post_bulk_delete, sender=MyModel)
    def handle_bulk_delete(sender, instances, pks, **kwargs):
        print(f"Deleted instances with PKs: {pks}")

For single-instance operations, use Django's built-in signals:
    from django.db.models.signals import post_save, post_delete

=============================================================================
TRIGGERING SIGNALS
=============================================================================

Use these when performing bulk operations or custom database updates
that bypass Django's normal signal system.

Example usage:
    from statezero.adaptors.django.signals import notify_updated, notify_bulk_deleted

    # After a bulk update
    MyModel.objects.filter(status='pending').update(status='complete')
    affected_instances = list(MyModel.objects.filter(status='complete'))
    notify_bulk_updated(affected_instances)

    # After deleting via raw SQL or QuerySet.delete()
    to_delete = list(MyModel.objects.filter(status='expired'))
    MyModel.objects.filter(status='expired').delete()
    notify_bulk_deleted(to_delete)

    # Or if you only have the PKs
    pks_to_delete = [1, 2, 3]
    MyModel.objects.filter(pk__in=pks_to_delete).delete()
    notify_bulk_deleted(MyModel, pks_to_delete)
"""

from typing import Any, List, Type, Union

from django.dispatch import Signal

from statezero.core.types import ActionType, ORMModel, ORMQuerySet


# =============================================================================
# Bulk Signals (for receiving)
# =============================================================================
# Django doesn't emit signals for bulk operations, so StateZero provides these.
# Use with Django's @receiver decorator.

post_bulk_create = Signal()  # Provides: sender, instances
post_bulk_update = Signal()  # Provides: sender, instances
post_bulk_delete = Signal()  # Provides: sender, instances, pks


# =============================================================================
# Internal Helpers
# =============================================================================


def _get_event_bus():
    """Get the configured event bus, raising helpful errors if not available."""
    from statezero.adaptors.django.config import config

    if config.event_bus is None:
        raise RuntimeError(
            "StateZero event bus is not initialized. "
            "Make sure StateZero is properly configured in your Django app."
        )
    return config.event_bus


def _get_registry():
    """Get the model registry."""
    from statezero.adaptors.django.config import registry
    return registry


def _validate_model_registered(model_class: Type[ORMModel]) -> None:
    """Validate that a model is registered with StateZero."""
    registry = _get_registry()
    if model_class not in registry._models_config:
        raise ValueError(
            f"Model '{model_class.__name__}' is not registered with StateZero. "
            f"Register it using Registry.register() before triggering signals."
        )


def _validate_instance(instance: Any, require_pk: bool = False) -> Type[ORMModel]:
    """
    Validate a model instance and return its model class.

    Parameters:
        instance: The model instance to validate
        require_pk: If True, raise an error if the instance has no PK

    Returns:
        The model class of the instance
    """
    if instance is None:
        raise ValueError("Instance cannot be None")

    if not hasattr(instance, '_meta'):
        raise TypeError(
            f"Expected a Django model instance, got {type(instance).__name__}. "
            f"Make sure you're passing a model instance, not a class or other object."
        )

    if require_pk and instance.pk is None:
        raise ValueError(
            f"Instance of {instance.__class__.__name__} has no primary key. "
            f"For update/delete signals, instances must be saved first."
        )

    return instance.__class__


def _validate_instances_list(
    instances: List[Any],
    require_pk: bool = False
) -> Type[ORMModel]:
    """
    Validate a list of instances and return the model class.

    Parameters:
        instances: List of model instances
        require_pk: If True, raise an error if any instance has no PK

    Returns:
        The model class of the instances
    """
    if not instances:
        raise ValueError(
            "Cannot trigger signal for empty list. "
            "If you have no instances to notify about, skip the signal call."
        )

    if not isinstance(instances, (list, tuple)):
        raise TypeError(
            f"Expected a list or tuple of instances, got {type(instances).__name__}. "
            f"If using a QuerySet, convert it to a list first with list(queryset)."
        )

    # Validate first instance to get model class
    first = instances[0]
    model_class = _validate_instance(first, require_pk=require_pk)

    # Validate all instances are same type
    for i, inst in enumerate(instances[1:], start=1):
        if not isinstance(inst, model_class):
            raise TypeError(
                f"All instances must be of the same model type. "
                f"Instance at index {i} is {type(inst).__name__}, "
                f"expected {model_class.__name__}."
            )
        if require_pk and inst.pk is None:
            raise ValueError(
                f"Instance at index {i} has no primary key. "
                f"For update/delete signals, all instances must be saved."
            )

    return model_class


# =============================================================================
# Single Instance Signals
# =============================================================================

def notify_created(instance: ORMModel) -> None:
    """
    Notify StateZero that an instance was created.

    Use this after creating an instance through means that bypass Django signals,
    such as raw SQL or bulk_create with ignore_conflicts.

    Parameters:
        instance: The created model instance (must have a PK)

    Raises:
        ValueError: If instance is None or has no PK
        TypeError: If instance is not a Django model
        RuntimeError: If StateZero is not configured

    Example:
        obj = MyModel.objects.raw('INSERT INTO ... RETURNING *')[0]
        notify_created(obj)
    """
    model_class = _validate_instance(instance, require_pk=True)
    _validate_model_registered(model_class)

    event_bus = _get_event_bus()
    event_bus.emit_event(ActionType.CREATE, instance)


def notify_updated(instance: ORMModel) -> None:
    """
    Notify StateZero that an instance was updated.

    Use this after updating an instance through means that bypass Django signals,
    such as QuerySet.update() or raw SQL.

    Parameters:
        instance: The updated model instance (must have a PK)

    Raises:
        ValueError: If instance is None or has no PK
        TypeError: If instance is not a Django model
        RuntimeError: If StateZero is not configured

    Example:
        MyModel.objects.filter(pk=obj.pk).update(status='active')
        obj.refresh_from_db()
        notify_updated(obj)
    """
    model_class = _validate_instance(instance, require_pk=True)
    _validate_model_registered(model_class)

    event_bus = _get_event_bus()
    event_bus.emit_event(ActionType.UPDATE, instance)


def notify_deleted(instance: ORMModel) -> None:
    """
    Notify StateZero that an instance was deleted.

    Use this after deleting an instance through means that bypass Django signals,
    such as QuerySet.delete() on a single object or raw SQL.

    Note: The instance should still have its PK value even after deletion.

    Parameters:
        instance: The deleted model instance (must have a PK)

    Raises:
        ValueError: If instance is None or has no PK
        TypeError: If instance is not a Django model
        RuntimeError: If StateZero is not configured

    Example:
        pk = obj.pk
        MyModel.objects.filter(pk=pk).delete()
        notify_deleted(obj)  # obj still has pk attribute
    """
    model_class = _validate_instance(instance, require_pk=True)
    _validate_model_registered(model_class)

    event_bus = _get_event_bus()
    event_bus.emit_event(ActionType.DELETE, instance)


# =============================================================================
# Bulk Signals
# =============================================================================

def notify_bulk_created(instances: List[ORMModel]) -> None:
    """
    Notify StateZero that multiple instances were created.

    Use this after bulk_create or other bulk insert operations.

    Parameters:
        instances: List of created instances (all must have PKs)

    Raises:
        ValueError: If instances is empty or any instance lacks a PK
        TypeError: If instances is not a list or instances aren't all the same model type
        RuntimeError: If StateZero is not configured

    Example:
        objs = MyModel.objects.bulk_create([
            MyModel(name='a'),
            MyModel(name='b'),
        ])
        notify_bulk_created(objs)
    """
    model_class = _validate_instances_list(instances, require_pk=True)
    _validate_model_registered(model_class)

    event_bus = _get_event_bus()
    event_bus.emit_bulk_event(ActionType.BULK_CREATE, instances)


def notify_bulk_updated(instances: Union[List[ORMModel], ORMQuerySet]) -> None:
    """
    Notify StateZero that multiple instances were updated.

    Use this after QuerySet.update() or bulk_update operations.

    Parameters:
        instances: List or QuerySet of updated instances (all must have PKs)

    Raises:
        ValueError: If instances is empty or any instance lacks a PK
        TypeError: If instances aren't all the same model type
        RuntimeError: If StateZero is not configured

    Example:
        MyModel.objects.filter(status='pending').update(status='complete')
        updated = MyModel.objects.filter(status='complete')
        notify_bulk_updated(updated)

        # Or with a list
        updated = list(MyModel.objects.filter(status='complete'))
        notify_bulk_updated(updated)
    """
    # Handle QuerySet - convert to list for validation
    if hasattr(instances, 'model'):
        instances = list(instances)

    model_class = _validate_instances_list(instances, require_pk=True)
    _validate_model_registered(model_class)

    event_bus = _get_event_bus()
    event_bus.emit_bulk_event(ActionType.BULK_UPDATE, instances)


def notify_bulk_deleted(
    model_or_instances: Union[Type[ORMModel], List[ORMModel]],
    pks: List[Any] = None
) -> None:
    """
    Notify StateZero that multiple instances were deleted.

    IMPORTANT: You must capture instances or PKs BEFORE deletion, since
    they won't be queryable afterward.

    Can be called in two ways:
    1. With instances captured before deletion: notify_bulk_deleted(instances)
    2. With model class and list of PKs: notify_bulk_deleted(MyModel, [1, 2, 3])

    Parameters:
        model_or_instances: Either a model class (with pks param) or list of instances
        pks: List of primary keys (only used when first param is a model class)

    Raises:
        ValueError: If instances/pks is empty
        TypeError: If arguments don't match expected patterns
        RuntimeError: If StateZero is not configured

    Example (with instances):
        to_delete = list(MyModel.objects.filter(status='expired'))
        MyModel.objects.filter(status='expired').delete()
        notify_bulk_deleted(to_delete)

    Example (with model + pks):
        pks_to_delete = [1, 2, 3]
        MyModel.objects.filter(pk__in=pks_to_delete).delete()
        notify_bulk_deleted(MyModel, pks_to_delete)
    """
    event_bus = _get_event_bus()

    # Case 1: Model class + pks
    if isinstance(model_or_instances, type) and hasattr(model_or_instances, '_meta'):
        model_class = model_or_instances

        if pks is None:
            raise ValueError(
                "When passing a model class, you must also provide a list of PKs. "
                "Usage: notify_bulk_deleted(MyModel, [pk1, pk2, ...])"
            )

        if not pks:
            raise ValueError(
                "Cannot trigger delete signal for empty list of PKs. "
                "If nothing was deleted, skip the signal call."
            )

        if not isinstance(pks, (list, tuple)):
            raise TypeError(
                f"pks must be a list or tuple, got {type(pks).__name__}"
            )

        _validate_model_registered(model_class)

        # Create unsaved model instances with just the PK set
        pseudo_instances = [model_class(pk=pk) for pk in pks]
        event_bus.emit_bulk_event(ActionType.BULK_DELETE, pseudo_instances)
        return

    # Case 2: List of instances
    if pks is not None:
        raise TypeError(
            "The 'pks' parameter should only be used when the first argument "
            "is a model class. When passing instances, PKs are read from them."
        )

    model_class = _validate_instances_list(model_or_instances, require_pk=True)
    _validate_model_registered(model_class)

    event_bus.emit_bulk_event(ActionType.BULK_DELETE, model_or_instances)
