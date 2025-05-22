import logging

import fakeredis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
import warnings

from statezero.adaptors.django.query_optimizer import DjangoQueryOptimizer
from statezero.adaptors.django.context_manager import query_timeout
from statezero.core.config import AppConfig, Registry

logger = logging.getLogger(__name__)

class DjangoLocalConfig(AppConfig):
    def __init__(self):
        self.DEBUG = settings.DEBUG

    def initialize(self):
        from statezero.adaptors.django.event_emitters import \
            DjangoPusherEventEmitter, DjangoConsoleEventEmitter
        from statezero.adaptors.django.extensions.custom_field_serializers.money_field import (
            MoneyFieldSchema, MoneyFieldSerializer)
        from statezero.adaptors.django.orm import DjangoORMAdapter
        from statezero.adaptors.django.schemas import DjangoSchemaGenerator
        from statezero.adaptors.django.serializers import DRFDynamicSerializer
        from statezero.adaptors.django.search_providers.basic_search import BasicSearchProvider
        from statezero.core.event_bus import EventBus

        # Initialize serializer, schema generator, and ORM adapter.
        self.serializer = DRFDynamicSerializer()
        self.schema_generator = DjangoSchemaGenerator()
        self.orm_provider = DjangoORMAdapter()
        self.context_manager = query_timeout
        self.query_optimizer = DjangoQueryOptimizer

        # Hot path
        self.hot_path_enabled = True
        self.trusted_group_resolver = lambda req: str(req.user.pk)

        # Instantiate emitters by injecting only the necessary functions.
        if hasattr(settings, 'STATEZERO_PUSHER'):
            event_emitter = DjangoPusherEventEmitter()
        else:
            warnings.warn("You have not added STATEZERO_PUSHER to your settings.py. Live model changes will not be broadcast")
            event_emitter = DjangoConsoleEventEmitter()
        
        # Create the EventBus with two explicit emitters.
        self.event_bus = EventBus(
            broadcast_emitter=event_emitter,
            orm_provider=self.orm_provider,
        )

        # Setup the search provider
        self.search_provider = BasicSearchProvider()

        # Explicitly register event signals after both components are configured.
        self.orm_provider.register_event_signals(self.event_bus)

        try:
            from djmoney.models.fields import MoneyField

            self.custom_serializers = {
                MoneyField: MoneyFieldSerializer,
            }
            self.schema_overrides = {
                MoneyField: MoneyFieldSchema,
            }
        except Exception:
            pass


# Create the singleton instances.
custom_config_path = getattr(settings, "STATEZERO_CUSTOM_CONFIG", None)
if custom_config_path:
    custom_config_class = import_string(custom_config_path)
    if not issubclass(custom_config_class, AppConfig):
        raise ImproperlyConfigured(
            "STATEZERO_CUSTOM_CONFIG must be a subclass of AppConfig"
        )
    config = custom_config_class()
else:
    config = DjangoLocalConfig()

registry = Registry()
