from statezero.core.context_storage import current_operation_id, current_canonical_id
import logging
from typing import Any, List, Type, Union
from fastapi.encoders import jsonable_encoder

from statezero.core.interfaces import AbstractEventEmitter, AbstractORMProvider
from statezero.core.types import ActionType, ORMModel, ORMQuerySet

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(
        self,
        broadcast_emitter: AbstractEventEmitter,
        orm_provider: AbstractORMProvider = None,
    ) -> None:
        """
        Initialize the EventBus with a broadcast emitter.

        Parameters:
        -----------
        broadcast_emitter: AbstractEventEmitter
            Emitter responsible for broadcasting events to clients
        orm_provider : AbstractORMProvider
            The orm provider to be used to get the default namespace for events
        """
        self.broadcast_emitter: AbstractEventEmitter = broadcast_emitter
        self.orm_provider = orm_provider

    def set_registry(self, registry):
        """Set the model registry after initialization if needed."""
        from statezero.core.config import Registry

        self.registry: Registry = registry

    def emit_event(self, action_type: ActionType, instance: Any) -> None:
        """
        Emit an event for a model instance to appropriate namespaces.

        Parameters:
        -----------
        action_type: ActionType
            The type of event (CREATE, UPDATE, DELETE)
        instance: Any
            The model instance that triggered the event
        """
        # Unused actions, no need to broadcast
        if action_type in (ActionType.PRE_DELETE, ActionType.PRE_UPDATE):
            return

        if not self.broadcast_emitter or not self.orm_provider:
            return

        try:
            # Get model class and registry config
            model_class = instance.__class__
            model_config = None

            # Use the registry to get model config
            if self.registry:
                try:
                    model_config = self.registry.get_config(model_class)
                except ValueError:
                    pass

            default_namespace = self.orm_provider.get_model_name(model_class)
            namespaces = [default_namespace]

            # Create payload data from instance
            model_name = self.orm_provider.get_model_name(instance)
            pk_field_name = instance._meta.pk.name
            pk_value = instance.pk

            data = {
                "event": action_type.value,
                "model": model_name,
                "operation_id": current_operation_id.get(),
                "canonical_id": current_canonical_id.get(),
                "instances": [pk_value],
                "pk_field_name": pk_field_name,
            }

            for namespace in namespaces:
                try:
                    # Emit data to this namespace
                    self.broadcast_emitter.emit(
                        namespace, action_type, jsonable_encoder(data)
                    )
                except Exception as e:
                    logger.exception(
                        "Error emitting to namespace %s for event %s: %s",
                        namespace,
                        action_type,
                        e,
                    )
        except Exception as e:
            logger.exception(
                "Error in broadcast emitter dispatching event %s for instance %s: %s",
                action_type,
                instance,
                e,
            )

    def emit_bulk_event(
        self, action_type: ActionType, instances: Union[List[Any], ORMQuerySet]
    ) -> None:
        """
        Emit a bulk event for multiple instances.

        Parameters:
        -----------
        action_type: ActionType
            The type of bulk event (e.g., BULK_UPDATE, BULK_DELETE)
        instances: Union[List[Any], ORMQuerySet]
            The instances affected by the bulk operation (can be a list or queryset)
        """
        # Convert QuerySet to list if needed
        if hasattr(instances, "all") and callable(getattr(instances, "all")):
            instances = list(instances)

        if not instances:
            return

        # Get the model class from the first instance
        first_instance = instances[0]
        # Use _meta.model to get the actual Django model class
        # This handles both real instances and pseudo-instances (from notify_bulk_deleted with pks)
        if hasattr(first_instance, "_meta") and hasattr(first_instance._meta, "model"):
            model_class = first_instance._meta.model
        else:
            model_class = first_instance.__class__

        # Dispatch Django-style signal for receivers
        self._dispatch_bulk_signal(action_type, model_class, instances)

        if not self.broadcast_emitter or not self.orm_provider:
            return

        try:
            # Get model config
            model_config = None
            if hasattr(self, "registry"):
                try:
                    model_config = self.registry.get_config(model_class)
                except (ValueError, AttributeError):
                    pass

            default_namespace = self.orm_provider.get_model_name(model_class)

            # Create payload data from instances
            model_name = self.orm_provider.get_model_name(first_instance)
            pk_field_name = first_instance._meta.pk.name
            pks = [instance.pk for instance in instances]

            data = {
                "event": action_type.value,
                "model": model_name,
                "operation_id": current_operation_id.get(),
                "canonical_id": current_canonical_id.get(),
                "instances": pks,
                "pk_field_name": pk_field_name,
            }

            # Create a dictionary to group instances by namespace
            namespaces = ["global", default_namespace]

            for namespace in namespaces:
                try:
                    # Emit data to this namespace
                    self.broadcast_emitter.emit(
                        namespace, action_type, jsonable_encoder(data)
                    )
                except Exception as e:
                    logger.exception(
                        "Error emitting bulk event to namespace %s: %s",
                        namespace,
                        e,
                    )
        except Exception as e:
            logger.exception(
                "Error in broadcast emitter dispatching bulk event %s: %s",
                action_type,
                e,
            )

    def _dispatch_bulk_signal(
        self, action_type: ActionType, model_class: Type, instances: List[Any]
    ) -> None:
        """
        Dispatch Django-style signals for bulk operations.

        Parameters:
        -----------
        action_type: ActionType
            The type of bulk event
        model_class: Type
            The model class of the instances
        instances: List[Any]
            The instances affected by the bulk operation
        """
        try:
            from statezero.adaptors.django.signals import (
                post_bulk_create,
                post_bulk_update,
                post_bulk_delete,
            )

            signal_map = {
                ActionType.BULK_CREATE: post_bulk_create,
                ActionType.BULK_UPDATE: post_bulk_update,
                ActionType.BULK_DELETE: post_bulk_delete,
            }

            signal = signal_map.get(action_type)
            if signal:
                # For delete, also include PKs since instances may be pseudo-objects
                if action_type == ActionType.BULK_DELETE:
                    pks = [inst.pk for inst in instances]
                    signal.send(
                        sender=model_class,
                        instances=instances,
                        pks=pks,
                    )
                else:
                    signal.send(sender=model_class, instances=instances)
        except Exception as e:
            logger.exception(
                "Error dispatching bulk signal %s: %s",
                action_type,
                e,
            )
