import json
import logging
from typing import Callable, Type, Dict, List, Any, Optional
from pydantic import BaseModel

from statezero.core.context_storage import current_operation_id
from statezero.core.interfaces import AbstractEventEmitter
from statezero.core.types import ActionType, ORMModel, RequestType

logger = logging.getLogger(__name__)


class EventPayload(BaseModel):
    event: str
    model: str
    operation_id: Optional[str]
    instances: List[Any]
    pk_field_name: str

class HotPathEvent(BaseModel):
    operation_id: Optional[str]
    ast: dict
    model: Optional[str]

class ConsoleEventEmitter(AbstractEventEmitter):
    def __init__(
        self,
        get_model_name: Callable[[ORMModel], str],  # type:ignore
    ) -> None:
        """
        :param get_model_name: A function that takes an ORMModel instance and returns its model name.
        :param get_namespace: A function that takes an ActionType and an ORMModel instance and returns a namespace.
        """
        self.get_model_name = get_model_name

    def has_permission(self, request: RequestType, namespace: str) -> bool:
        return True

    def emit(
        self, namespace: str, event_type: ActionType, instance: Type[ORMModel]
    ) -> None:  # type:ignore
        
        model_name = self.get_model_name(instance)
        # Get the actual primary key field name
        pk_field_name = instance._meta.pk.name
        pk_value = instance.pk
        
        # Use the standardized payload structure
        payload = EventPayload(
            event=event_type.value,
            model=model_name,
            operation_id=current_operation_id.get(),
            instances=[pk_value],
            pk_field_name=pk_field_name
        )
        
        logger.info(f"Event emitted: {json.dumps(payload.model_dump())}")

    def emit_bulk(
        self,
        namespace: str,
        event_type: ActionType,
        model_class: Type[ORMModel],
        instances: List[ORMModel],
    ) -> None:
        """
        Emit a bulk event to the given namespace.
        Aggregates events for each instance into a single log message.
        """
        if not instances:
            return
            
        model_name = self.get_model_name(instances[0])
        pk_field_name = instances[0]._meta.pk.name
        pks = [instance.pk for instance in instances]
        
        # Use the standardized payload structure
        payload = EventPayload(
            event=event_type.value,
            model=model_name,
            operation_id=current_operation_id.get(),
            instances=pks,
            pk_field_name=pk_field_name
        )
        
        logger.info(f"Bulk event emitted to namespace '{namespace}': {payload.model_dump()}")

    def emit_hot_path_event(self, trusted_group: str, event_data: HotPathEvent) -> None:
        logger.info(f"Emitted to trusted group '{trusted_group}': {event_data.model_dump()}")

    def authenticate(self, request: RequestType) -> None:
        channel = request.data.get("channel_name")
        socket_id = request.data.get("socket_id")
        logger.debug(
            f"Console authentication for channel '{channel}' and socket_id '{socket_id}'"
        )
        pass


class PusherEventEmitter(AbstractEventEmitter):
    def __init__(
        self,
        pusher_client,
        get_model_name: Callable[[ORMModel], str],  # type:ignore
    ) -> None:
        """
        :param pusher_client: An initialized Pusher client.
        :param get_model_name: A function that takes an ORMModel instance and returns its model name.
        :param get_namespace: A function that takes an ActionType and an ORMModel instance and returns a namespace.
        """
        self.pusher_client = pusher_client
        self.get_model_name = get_model_name

    def has_permission(self, request: RequestType, namespace: str) -> bool:
        return True

    def emit(
        self, namespace: str, event_type: ActionType, instance: Type[ORMModel]
    ) -> None:  # type:ignore
        channel = f"private-{namespace}"
        model_name = self.get_model_name(instance)

        # Get the actual primary key field name
        pk_field_name = instance._meta.pk.name
        pk_value = instance.pk

        payload = EventPayload(
            event=event_type.value,
            model=model_name,
            operation_id=current_operation_id.get(),
            instances=[pk_value],
            pk_field_name=pk_field_name
        )

        try:
            self.pusher_client.trigger(channel, event_type.value, payload.model_dump())
        except Exception as e:
            logger.error(
                f"Error emitting event '{event_type.value}' on channel '{channel}': {e}"
            )

    def emit_bulk(
        self,
        namespace: str,
        event_type: ActionType,
        model_class: Type[ORMModel],
        instances: List[ORMModel],
    ) -> None:
        channel = f"private-{namespace}"
        
        if len(instances) < 1:
            return
        
        # Collect only the primary key values
        pks = [instance.pk for instance in instances]
        pk_field_name = instances[0]._meta.pk.name

        payload = EventPayload(
            event=event_type.value,
            model=self.get_model_name(instances[0]),
            operation_id=current_operation_id.get(),
            instances=pks,
            pk_field_name=pk_field_name
        )
        
        try:
            self.pusher_client.trigger(channel, event_type.value, payload.model_dump())
        except Exception as e:
            logger.error(f"Error emitting bulk event on channel '{channel}': {e}")

    def emit_hot_path_event(self, trusted_group: str, event: str, event_data: HotPathEvent) -> None:
        """ Emit an event to the hot path """

        try:
            self.pusher_client.trigger(f'private-hotpath-{trusted_group}', event, event_data.model_dump())
        except Exception as e:
            logger.error(f"Error emitting hot path event on channel '{trusted_group}': {e}")

    def authenticate(self, request: RequestType) -> dict:
        channel = request.data.get("channel_name")
        socket_id = request.data.get("socket_id")
        logger.debug(
            f"Pusher authentication for channel '{channel}' and socket_id '{socket_id}'"
        )
        return self.pusher_client.authenticate(channel=channel, socket_id=socket_id)