import logging

import fakeredis
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from modelsync.core.config import AppConfig, Registry

logger = logging.getLogger(__name__)


class DjangoLocalConfig(AppConfig):
    def __init__(self):
        self.DEBUG = settings.DEBUG

    def initialize(self):
        from modelsync.adaptors.django.event_emitters import \
            DjangoPusherEventEmitter
        from modelsync.adaptors.django.extensions.custom_field_serializers.money_field import (
            MoneyFieldSchema, MoneyFieldSerializer)
        from modelsync.adaptors.django.orm import DjangoORMAdapter
        from modelsync.adaptors.django.schemas import DjangoSchemaGenerator
        from modelsync.adaptors.django.serializers import DRFDynamicSerializer
        from modelsync.adaptors.django.search_providers.basic_search import BasicSearchProvider
        from modelsync.adaptors.django.caching import DjangoCacheBackend, DjangoDependencyStore
        from modelsync.core.caching import (CacheInvalidationEmitter,
                                            RedisCacheBackend,
                                            RedisDependencyStore)
        from modelsync.core.event_bus import EventBus

        # Initialize serializer, schema generator, and ORM adapter.
        self.serializer = DRFDynamicSerializer()
        self.schema_generator = DjangoSchemaGenerator()
        self.orm_provider = DjangoORMAdapter()

        # Set up cache backends based on settings
        cache_config = getattr(settings, 'MODELSYNC_CACHE', {})
        cache_name = cache_config.get('NAME', 'default')
        default_ttl = cache_config.get('DEFAULT_TTL', None)
        
        # Use Django's caching framework
        if settings.CACHES.get(cache_name):
            logger.info(f"Using Django cache backend '{cache_name}' for ModelSync")
            self.cache_backend = DjangoCacheBackend(cache_name=cache_name, default_ttl=default_ttl)
            self.dependency_store = DjangoDependencyStore(cache_name=cache_name)
        else:
            # Fall back to fakeredis if the specified cache is not configured
            logger.warning(f"Django cache '{cache_name}' not configured, falling back to fakeredis")
            import fakeredis
            from modelsync.core.caching import RedisCacheBackend, RedisDependencyStore
            
            redis_client = fakeredis.FakeStrictRedis()
            self.cache_backend = RedisCacheBackend(redis_client, default_ttl=default_ttl)
            self.dependency_store = RedisDependencyStore(redis_client)

        # Instantiate emitters by injecting only the necessary functions.
        event_emitter = DjangoPusherEventEmitter()
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
custom_config_path = getattr(settings, "MODELSYNC_CUSTOM_CONFIG", None)
if custom_config_path:
    custom_config_class = import_string(custom_config_path)
    if not issubclass(custom_config_class, AppConfig):
        raise ImproperlyConfigured(
            "MODELSYNC_CUSTOM_CONFIG must be a subclass of AppConfig"
        )
    config = custom_config_class()
else:
    config = DjangoLocalConfig()

registry = Registry()
