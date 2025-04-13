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
        from statezero.core.caching import (CacheInvalidationEmitter,
                                            RedisCacheBackend)
        from statezero.core.event_bus import EventBus

        # Initialize serializer, schema generator, and ORM adapter.
        self.serializer = DRFDynamicSerializer()
        self.schema_generator = DjangoSchemaGenerator()
        self.orm_provider = DjangoORMAdapter()
        self.context_manager = query_timeout
        self.query_optimizer = DjangoQueryOptimizer

        # Set up cache backends based on settings
        cache_config = getattr(settings, 'STATEZERO_CACHE', {})
        default_ttl = cache_config.get('DEFAULT_TTL', None)

        # Try to get Redis client from Django's cache configuration
        redis_client = None
        cache_name = cache_config.get('NAME', 'default')

        if settings.CACHES.get(cache_name):
            django_cache = settings.CACHES.get(cache_name)
            backend = django_cache.get('BACKEND', '')
            
            # Check if it's a Redis-based cache
            if 'redis' in backend.lower():
                logger.info(f"Using Redis from Django cache '{cache_name}' for StateZero")
                try:
                    from django_redis import get_redis_connection
                    redis_client = get_redis_connection(cache_name)
                except (ImportError, Exception) as e:
                    logger.warning(f"Could not get Redis connection from Django cache: {e}")
            else:
                logger.warning(f"Django cache '{cache_name}' is not Redis-based, using fakeredis instead")

        # If no Redis client was obtained, use fakeredis
        if redis_client is None:
            logger.warning("Using fakeredis for StateZero caching - data will not persist between restarts")
            import fakeredis
            redis_client = fakeredis.FakeStrictRedis()

        # Create the Redis cache backend
        self.cache_backend = RedisCacheBackend(redis_client, default_ttl=default_ttl)        

        # Instantiate emitters by injecting only the necessary functions.
        if hasattr(settings, 'STATEZERO_PUSHER'):
            event_emitter = DjangoPusherEventEmitter()
        else:
            warnings.warn("You have not added STATEZERO_PUSHER to your settings.py. Live model changes will not be broadcast")
            event_emitter = DjangoConsoleEventEmitter()
        
        
        cache_invalidation_emitter = CacheInvalidationEmitter(
            cache_backend=self.cache_backend,
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
