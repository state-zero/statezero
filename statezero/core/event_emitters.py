import json
import logging
from typing import Callable, Type, Dict, List, Any, Optional

from statezero.core.context_storage import current_operation_id
from statezero.core.interfaces import AbstractEventEmitter
from statezero.core.types import ActionType, ORMModel, RequestType

logger = logging.getLogger(__name__)


class ConsoleEventEmitter(AbstractEventEmitter):
    def __init__(self) -> None:
        pass

    def has_permission(self, request: RequestType, namespace: str) -> bool:
        return True

    def emit(
        self, 
        namespace: str,
        event_type: ActionType, 
        data: Dict[str, Any]
    ) -> None:
        logger.info(f"Event emitted to namespace '{namespace}': {json.dumps(data)}")

    def authenticate(self, request: RequestType) -> None:
        channel = request.data.get("channel_name")
        socket_id = request.data.get("socket_id")
        logger.debug(f"Console authentication for channel '{channel}' and socket_id '{socket_id}'")


class PusherEventEmitter(AbstractEventEmitter):
    def __init__(
        self,
        pusher_client,
    ) -> None:
        self.pusher_client = pusher_client

    def has_permission(self, request: RequestType, namespace: str) -> bool:
        return True

    def emit(
        self, 
        namespace: str,
        event_type: ActionType, 
        data: Dict[str, Any]
    ) -> None:
        channel = f"private-{namespace}"
        
        try:
            self.pusher_client.trigger(channel, event_type.value, data)
        except Exception as e:
            logger.error(f"Error emitting event '{event_type.value}' on channel '{channel}': {e}")

    def authenticate(self, request: RequestType) -> dict:
        channel = request.data.get("channel_name")
        socket_id = request.data.get("socket_id")
        logger.debug(f"Pusher authentication for channel '{channel}' and socket_id '{socket_id}'")
        return self.pusher_client.authenticate(channel=channel, socket_id=socket_id)
