from typing import Optional
import logging
from django.conf import settings
from rest_framework.request import Request
from django.utils.module_loading import import_string

from statezero.core.event_emitters import ConsoleEventEmitter, PusherEventEmitter

logger = logging.getLogger(__name__)


class DjangoConsoleEventEmitter(ConsoleEventEmitter):
    def __init__(self) -> None:
        super().__init__()
        
        permission_class_path = getattr(
            settings,
            "STATEZERO_VIEW_ACCESS_CLASS",
            "rest_framework.permissions.IsAuthenticated",
        )
        try:
            self.permission_class = import_string(permission_class_path)()
            logger.debug("Using emitter permission class: %s", permission_class_path)
        except Exception as e:
            logger.error("Error importing emitter permission class '%s': %s", permission_class_path, str(e))
            from rest_framework.permissions import IsAuthenticated
            self.permission_class = IsAuthenticated()

    def has_permission(self, request: Request, namespace: str) -> bool:
        return self.permission_class.has_permission(request, None)


class DjangoPusherEventEmitter(PusherEventEmitter):
    def __init__(
        self,
        app_id: Optional[str] = None,
        key: Optional[str] = None,
        secret: Optional[str] = None,
        cluster: Optional[str] = None,
    ) -> None:
        import pusher
        
        app_id = app_id or settings.STATEZERO_PUSHER.get("APP_ID")
        key = key or settings.STATEZERO_PUSHER.get("KEY")
        secret = secret or settings.STATEZERO_PUSHER.get("SECRET")
        cluster = cluster or settings.STATEZERO_PUSHER.get("CLUSTER")
        
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
        
        super().__init__(pusher_client=pusher_client)
        
        permission_class_path = getattr(
            settings,
            "STATEZERO_VIEW_ACCESS_CLASS",
            "rest_framework.permissions.IsAuthenticated",
        )
        try:
            self.permission_class = import_string(permission_class_path)()
            logger.debug("Using emitter permission class: %s", permission_class_path)
        except Exception as e:
            logger.error("Error importing emitter permission class '%s': %s", permission_class_path, str(e))
            from rest_framework.permissions import IsAuthenticated
            self.permission_class = IsAuthenticated()

    def has_permission(self, request: Request, namespace: str) -> bool:
        return self.permission_class.has_permission(request, None)