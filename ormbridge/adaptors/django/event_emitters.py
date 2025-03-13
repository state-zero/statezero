from typing import Optional, Type

import pusher
from django.conf import settings
from rest_framework.request import Request

from ormbridge.adaptors.django.config import config
from ormbridge.core.event_emitters import (ConsoleEventEmitter,
                                           PusherEventEmitter)
from ormbridge.core.types import ActionType, ORMModel


class DjangoConsoleEventEmitter(ConsoleEventEmitter):
    def __init__(self) -> None:
        """
        Instantiate the Django console emitter by injecting the Django-specific get_model_name
        and get_namespace functions.
        """
        super().__init__(get_model_name=config.orm_provider.get_model_name)

    def has_permission(self, request: Request, namespace: str) -> bool:
        # Use Django's user authentication system.
        return request.user.is_authenticated


class DjangoPusherEventEmitter(PusherEventEmitter):
    def __init__(
        self,
        app_id: Optional[str] = None,
        key: Optional[str] = None,
        secret: Optional[str] = None,
        cluster: Optional[str] = None,
    ) -> None:
        """
        Instantiate the Django Pusher emitter by resolving credentials from parameters or settings
        and injecting the Django-specific get_model_name and get_namespace functions.
        """
        app_id = app_id or settings.ORMBRIDGE_PUSHER.get("APP_ID")
        key = key or settings.ORMBRIDGE_PUSHER.get("KEY")
        secret = secret or settings.ORMBRIDGE_PUSHER.get("SECRET")
        cluster = cluster or settings.ORMBRIDGE_PUSHER.get("CLUSTER")
        if not all([app_id, key, secret, cluster]):
            raise ValueError(
                "Pusher credentials must be provided via parameters or defined in settings as "
                "'APP_ID', 'KEY', 'SECRET', and 'CLUSTER'."
            )
        pusher_client = pusher.Pusher(
            app_id=app_id,
            key=key,
            secret=secret,
            cluster=cluster,
            ssl=True,
        )
        super().__init__(
            pusher_client=pusher_client,
            get_model_name=config.orm_provider.get_model_name,
        )

    def has_permission(self, request: Request, namespace: str) -> bool:
        # Use Django's user authentication system.
        return request.user.is_authenticated
