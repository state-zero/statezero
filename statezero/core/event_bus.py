from statezero.core.context_storage import current_operation_id, current_canonical_id
import logging
from typing import Any, Type, Union, List
from fastapi.encoders import jsonable_encoder

from statezero.core.interfaces import AbstractEventEmitter, AbstractORMProvider
from statezero.core.types import ActionType, ORMModel, ORMQuerySet
from statezero.core.subscription_processor import process_model_change

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
            process_model_change(instance, action_type.value, self.orm_provider, self.registry)
        except Exception as e:
            logger.exception(
                "Error processing subscription changes for %s event: %s",
                action_type,
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

        if not self.broadcast_emitter or not self.orm_provider:
            return

        try:
            # Process each instance through subscription processor
            for instance in instances:
                try:
                    process_model_change(instance, action_type.value, self.orm_provider, self.registry)
                except Exception as e:
                    logger.exception("Error processing subscription changes for bulk event: %s", e)
        except Exception as e:
            logger.exception(
                "Error in broadcast emitter dispatching bulk event %s: %s",
                action_type,
                e,
            )
