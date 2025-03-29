import logging

import fakeredis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
import warnings

from ormbridge.adaptors.django.context_manager import query_timeout
from ormbridge.core.config import AppConfig, Registry
from ormbridge.adaptors.django.query_optimizer import optimize_query

logger = logging.getLogger(__name__)

class DjangoLocalConfig(AppConfig):
    def __init__(self):
        self.DEBUG = settings.DEBUG

    def initialize(self):
        from ormbridge.adaptors.django.event_emitters import \
            DjangoPusherEventEmitter, DjangoConsoleEventEmitter
        from ormbridge.adaptors.django.extensions.custom_field_serializers.money_field import (
            MoneyFieldSchema, MoneyFieldSerializer)
        from ormbridge.adaptors.django.orm import DjangoORMAdapter
        from ormbridge.adaptors.django.schemas import DjangoSchemaGenerator
        from ormbridge.adaptors.django.serializers import DRFDynamicSerializer
        from ormbridge.adaptors.django.search_providers.basic_search import BasicSearchProvider
        from ormbridge.adaptors.django.caching import DjangoCacheBackend, DjangoDependencyStore
        from ormbridge.core.caching import (CacheInvalidationEmitter,
                                            RedisCacheBackend,
                                            RedisDependencyStore)
        from ormbridge.core.event_bus import EventBus

        # Initialize serializer, schema generator, and ORM adapter.
        self.serializer = DRFDynamicSerializer()
        self.schema_generator = DjangoSchemaGenerator()
        self.orm_provider = DjangoORMAdapter()
        self.context_manager = query_timeout
        self.selected_fields_query_optimizer = optimize_query

        # Set up cache backends based on settings
        cache_config = getattr(settings, 'ORMBRIDGE_CACHE', {})
        cache_name = cache_config.get('NAME', 'default')
        default_ttl = cache_config.get('DEFAULT_TTL', None)
        
        # Use Django's caching framework
        if settings.CACHES.get(cache_name):
            logger.info(f"Using Django cache backend '{cache_name}' for ORMBridge")
            self.cache_backend = DjangoCacheBackend(cache_name=cache_name, default_ttl=default_ttl)
            self.dependency_store = DjangoDependencyStore(cache_name=cache_name)
        else:
            # Fall back to fakeredis if the specified cache is not configured
            logger.warning(f"Django cache '{cache_name}' not configured, falling back to fakeredis")
            import fakeredis
            from ormbridge.core.caching import RedisCacheBackend, RedisDependencyStore
            
            redis_client = fakeredis.FakeStrictRedis()
            self.cache_backend = RedisCacheBackend(redis_client, default_ttl=default_ttl)
            self.dependency_store = RedisDependencyStore(redis_client)

        # Instantiate emitters by injecting only the necessary functions.
        if hasattr(settings, 'ORMBRIDGE_PUSHER'):
            event_emitter = DjangoPusherEventEmitter()
        else:
            warnings.warn("You have not added ORMBRIDGE_PUSHER to your settings.py. Live model changes will not be broadcast")
            event_emitter = DjangoConsoleEventEmitter()
        
        
        cache_invalidation_emitter = CacheInvalidationEmitter(
            cache_backend=self.cache_backend,
            dependency_store=self.dependency_store,
            get_model_name=self.orm_provider.get_model_name,
        )

        # Create the EventBus with two explicit emitters.
        self.event_bus = EventBus(
            cache_invalidation_emitter=cache_invalidation_emitter,
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
custom_config_path = getattr(settings, "ORMBRIDGE_CUSTOM_CONFIG", None)
if custom_config_path:
    custom_config_class = import_string(custom_config_path)
    if not issubclass(custom_config_class, AppConfig):
        raise ImproperlyConfigured(
            "ORMBRIDGE_CUSTOM_CONFIG must be a subclass of AppConfig"
        )
    config = custom_config_class()
else:
    config = DjangoLocalConfig()

registry = Registry()
