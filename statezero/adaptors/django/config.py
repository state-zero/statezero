import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string
import warnings

from statezero.adaptors.django.query_optimizer import DjangoQueryOptimizer
from statezero.adaptors.django.context_manager import query_timeout
from statezero.core.config import AppConfig, Registry
from django.db.models import FileField

try:
    from django.db.models import ImageField
    image_field_available = True
except ImportError:
    ImageField = None
    image_field_available = False

logger = logging.getLogger(__name__)

class DjangoLocalConfig(AppConfig):
    def __init__(self):
        self.DEBUG = settings.DEBUG
        self.enable_telemetry = getattr(settings, 'STATEZERO_ENABLE_TELEMETRY', False)
        self.default_limit = getattr(settings, 'STATEZERO_DEFAULT_LIMIT', None)

    def initialize(self):
        from statezero.adaptors.django.event_emitters import \
            DjangoPusherEventEmitter, DjangoConsoleEventEmitter
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
        
        self.file_upload_callbacks = None

        # Explicitly register event signals after both components are configured.
        self.orm_provider.register_event_signals(self.event_bus)
        
        from statezero.adaptors.django.extensions.custom_field_serializers.file_fields import (
            FileFieldSerializer, ImageFieldSerializer)

        # Initialize custom serializers
        self.custom_serializers = {
            FileField: FileFieldSerializer
        }
        
        if image_field_available:
            self.custom_serializers[ImageField] = ImageFieldSerializer

        # Try to register djmoney support
        try:
            from statezero.adaptors.django.extensions.custom_field_serializers.money_field import (
            MoneyFieldSchema, MoneyFieldSerializer)
            from djmoney.models.fields import MoneyField
            self.custom_serializers[MoneyField] = MoneyFieldSerializer
            self.schema_overrides = {
                MoneyField: MoneyFieldSchema,
            }
        except Exception:
            self.schema_overrides = {}

        # Try to register django-pydantic-field support
        try:
            from django_pydantic_field.v2.fields import PydanticSchemaField
            from statezero.adaptors.django.extensions.custom_field_serializers.pydantic_field import (
                PydanticSchemaFieldSerializer)
            self.custom_serializers[PydanticSchemaField] = PydanticSchemaFieldSerializer
        except ImportError:
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
