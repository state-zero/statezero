import logging
from typing import Any, Type, Union, List

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
        Initialize the EventBus with two explicit event emitters:
          - broadcast_emitter: Handles broadcasting events to clients.

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

        This method:
        1. Determines applicable namespaces (default + additional)
        2. Emits the event to each namespace via the broadcast emitter

        Parameters:
        -----------
        action_type: ActionType
            The type of event (CREATE, UPDATE, DELETE)
        instance: Any
            The model instance that triggered the event
        """
        # Unused actions, no need to broadcast
        if action_type in (ActionType.PRE_DELETE, ActionType.PRE_UPDATE):
            pass 

        # Then handle broadcast with namespace resolution
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

            # Add partition-specific namespaces if configured
            if model_config and model_config.partition_fields:
                for field_name in model_config.partition_fields:
                    try:
                        partition_value = getattr(instance, field_name, None)
                        if partition_value is not None:
                            partition_namespace = f"{default_namespace}-{field_name}-{partition_value}"
                            namespaces.append(partition_namespace)
                    except Exception as e:
                        logger.warning(
                            "Could not resolve partition field '%s' for model %s: %s",
                            field_name, model_class.__name__, e
                        )

            for namespace in namespaces:
                try:
                    # Emit to this specific namespace
                    self.broadcast_emitter.emit(namespace, action_type, instance)
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

    def emit_bulk_event(self, action_type: ActionType, instances: Union[List[Any], ORMQuerySet]) -> None:
        """
        Emit a bulk event for multiple instances.
        
        This method:
        1. Groups instances by namespace
        2. Emits bulk events to each namespace with the appropriate instances
        
        Parameters:
        -----------
        action_type: ActionType
            The type of bulk event (e.g., BULK_UPDATE, BULK_DELETE)
        instances: Union[List[Any], ORMQuerySet]
            The instances affected by the bulk operation (can be a list or queryset)
        """
        # Convert QuerySet to list if needed
        if hasattr(instances, 'all') and callable(getattr(instances, 'all')):
            instances = list(instances)
            
        if not instances:
            return
            
        # Get the model class from the first instance
        first_instance = instances[0]
        model_class = first_instance.__class__

        # Handle broadcast with namespace resolution
        if not self.broadcast_emitter or not self.orm_provider:
            return

        try:
            # Get model config
            model_config = None
            if hasattr(self, 'registry'):
                try:
                    model_config = self.registry.get_config(model_class)
                except (ValueError, AttributeError):
                    pass

            # Create a dictionary to group instances by namespace
            # Use "global" as the universal key for all models
            namespaced_instances = {
                "global": instances
            }

            default_namespace = self.orm_provider.get_model_name(model_class)
            namespaced_instances[default_namespace] = instances

            # Add partition-specific groupings if configured
            if model_config and model_config.partition_fields:
                for field_name in model_config.partition_fields:
                    # Group instances by partition value for this field
                    partition_groups = {}
                    for instance in instances:
                        try:
                            partition_value = getattr(instance, field_name, None)
                            if partition_value is not None:
                                partition_namespace = f"{default_namespace}-{field_name}-{partition_value}"
                                if partition_namespace not in partition_groups:
                                    partition_groups[partition_namespace] = []
                                partition_groups[partition_namespace].append(instance)
                        except Exception as e:
                            logger.warning(
                                "Could not resolve partition field '%s' for instance: %s",
                                field_name, e
                            )
                    
                    # Add partition groups to namespaced_instances
                    namespaced_instances.update(partition_groups)

            for namespace, ns_instances in namespaced_instances.items():
                try:
                    self.broadcast_emitter.emit_bulk(
                        namespace=namespace,
                        event_type=action_type,
                        model_class=model_class,
                        instances=ns_instances
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