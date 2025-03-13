import json
import logging
from typing import Callable, Type, Dict, List

from ormbridge.core.context_storage import current_operation_id
from ormbridge.core.interfaces import AbstractEventEmitter
from ormbridge.core.types import ActionType, ORMModel, RequestType

logger = logging.getLogger(__name__)


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
        data = {
            "event": event_type.value,
            "model": model_name,
            "operation_id": current_operation_id.get(),
        }
        data[pk_field_name] = pk_value
        logger.info(f"Event emitted: {json.dumps(data)}")

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
        events = []
        for instance in instances:
            model_name = self.get_model_name(instance)
            pk_field_name = instance._meta.pk.name
            data = {
                "event": event_type.value,
                "model": model_name,
                "operation_id": current_operation_id.get(),
            }
            data[pk_field_name] = instance.pk
            events.append(data)
        logger.info(f"Bulk event emitted to namespace '{namespace}': {json.dumps(events)}")

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

        data = {
            "event": event_type.value,
            "model": model_name,
            "operation_id": current_operation_id.get(),
        }

        # Add the primary key using its actual field name
        data[pk_field_name] = pk_value

        try:
            self.pusher_client.trigger(channel, event_type.value, data)
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
        # Collect only the primary key values
        pks = [instance.pk for instance in instances]
        
        if len(pks) < 1:
            return
        
        pk_field_name = instances[0]._meta.pk.name

        payload = {
            "event": event_type.value,
            "model": self.get_model_name(instances[0]) if instances else "",
            "operation_id": current_operation_id.get(),
            "instances": pks,
            "pk_field_name": pk_field_name
        }
        try:
            self.pusher_client.trigger(channel, event_type.value, payload)
        except Exception as e:
            logger.error(f"Error emitting bulk event on channel '{channel}': {e}")

    def authenticate(self, request: RequestType) -> dict:
        channel = request.data.get("channel_name")
        socket_id = request.data.get("socket_id")
        logger.debug(
            f"Pusher authentication for channel '{channel}' and socket_id '{socket_id}'"
        )
        return self.pusher_client.authenticate(channel=channel, socket_id=socket_id)
