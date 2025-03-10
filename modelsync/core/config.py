from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union

from modelsync.core.classes import AdditionalField
from modelsync.core.event_bus import EventBus
from modelsync.core.interfaces import (AbstractCustomQueryset,
                                       AbstractDataSerializer,
                                       AbstractORMProvider, AbstractPermission,
                                       AbstractSchemaGenerator, AbstractSearchProvider)
from modelsync.core.types import ORMField

NamespaceResolver = Callable[[Any, str], Union[str, List[str], None]]


class AppConfig(ABC):
    """
    Global configuration for the system.
    Developers configure:
      - The global web engine (including serializer and schema generator)
      - The ORM provider (e.g. SQLAlchemyORMProvider, etc.)
      - The event emitter (e.g. FastAPIEventEmitter, etc.)

    Global overrides for both serializer and schema generation are provided,
    keyed by ORMField. These overrides apply to all models unless a per-model override
    is provided in the model's configuration.
    """

    serializer: Optional[AbstractDataSerializer] = None
    schema_generator: Optional[AbstractSchemaGenerator] = None

    # Global custom overrides for ALL models.
    custom_serializers: Dict[ORMField, Callable] = {}  # type:ignore
    schema_overrides: Dict[ORMField, dict] = {}  # type:ignore

    event_bus: EventBus = None
    default_limit: Optional[int] = 100
    orm_provider: AbstractORMProvider = None
    search_provider: AbstractSearchProvider = None

    def __init__(self) -> None:
        self._orm_provider: Optional[AbstractORMProvider] = None

    def configure(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise AttributeError(f"Invalid configuration key: {key}")

    @abstractmethod
    def initialize(self) -> None:
        """
        Initialize the global configuration for the system.

        This method sets up all core components needed by the framework, including:
        - The data serializer and schema generator.
        - The ORM provider for database interactions.
        - The event bus along with its associated event emitters.
        - Caching and dependency tracking mechanisms.

        It must be implemented by each subclass of AppConfig to ensure that all required
        components are properly configured and wired together before the application starts
        processing requests.

        Raises:
            NotImplementedError: If the method is not implemented in a subclass.
        """
        pass


class ModelConfig:
    """
    Initialize model-specific configuration.

    Parameters:
    -----------
    model: Type
        The model class to register
    custom_querysets: Dict[str, Type[AbstractCustomQueryset]], optional
        Custom queryset methods for this model
    permissions: List[Type[AbstractPermission]], optional
        Permission classes that control access to this model
    pre_hooks: List[Callable], optional
        Functions to run before serialization/deserialization
    post_hooks: List[Callable], optional
        Functions to run after serialization/deserialization
    additional_fields: List[AdditionalField], optional
        Additional computed fields to add to the model schema
    cache_enabled: bool, default=False
        Whether to enable caching for this model
    anonymous_read_allowed: bool, default=False
        Whether unauthenticated users can read this model
    filterable_fields: Set[str], optional
        Fields that can be used in filter queries
    searchable_fields: Set[str], optional
        Fields that can be used in search queries
    ordering_fields: Set[str], optional
        Fields that can be used for ordering
    additional_namespace_resolvers: List[NamespaceResolver], optional
        Functions that generate additional event namespaces beyond the default model namespace.
        Each resolver receives (instance, action) parameters and should return a string,
        list of strings, or None. The 'instance' is the model instance being affected,
        and 'action' is one of 'create', 'update', or 'delete'.
    DEBUG: bool, default=False
        Enable debug mode for this model
    """

    def __init__(
        self,
        model: Type,
        custom_querysets: Optional[Dict[str, Type[AbstractCustomQueryset]]] = None,
        permissions: Optional[List[Type[AbstractPermission]]] = None,
        pre_hooks: Optional[List] = None,
        post_hooks: Optional[List] = None,
        additional_fields: Optional[List[AdditionalField]] = None,
        cache_enabled: bool = False,
        anonymous_read_allowed: bool = False,
        filterable_fields: Optional[Set[str]] = None,
        searchable_fields: Optional[Set[str]] = None,
        ordering_fields: Optional[Set[str]] = None,
        additional_namespace_resolvers: NamespaceResolver = None,
        DEBUG: bool = False,
    ):
        self.model = model
        self._custom_querysets = custom_querysets or {}
        self._permissions = permissions or []
        self.pre_hooks = pre_hooks or []
        self.post_hooks = post_hooks or []
        self.additional_fields = additional_fields or []
        self.cache_enabled = cache_enabled
        self.anonymous_read_allowed = anonymous_read_allowed
        self.filterable_fields = filterable_fields or set()
        self.searchable_fields = searchable_fields or set()
        self.ordering_fields = ordering_fields or set()
        self.additional_namespace_resolvers = additional_namespace_resolvers or []
        self.DEBUG = DEBUG or False

    @property
    def permissions(self):
        """Resolve permission class strings to actual classes on each access"""
        resolved = []
        for perm in self._permissions:
            if isinstance(perm, str):
                from django.utils.module_loading import import_string
                try:
                    perm_class = import_string(perm)
                    resolved.append(perm_class)
                except ImportError:
                    raise ImportError(f"Could not import permission class: {perm}")
            else:
                resolved.append(perm)
        return resolved

    @property
    def custom_querysets(self):
        """Resolve queryset class strings to actual classes on each access"""
        resolved = {}
        for key, queryset in self._custom_querysets.items():
            if isinstance(queryset, str):
                from django.utils.module_loading import import_string
                try:
                    qs_class = import_string(queryset)
                    resolved[key] = qs_class
                except ImportError:
                    raise ImportError(f"Could not import queryset class: {queryset}")
            else:
                resolved[key] = queryset
        return resolved


        


class Registry:
    """
    Global registry mapping models to their ModelConfig.
    """

    _models_config: Dict[Type, ModelConfig] = {}

    @classmethod
    def register(cls, model: Type, config: ModelConfig) -> None:
        if model in cls._models_config:
            raise ValueError(f"Model {model.__name__} is already registered.")
        cls._models_config[model] = config

    @classmethod
    def get_config(cls, model: Type) -> ModelConfig:
        config = cls._models_config.get(model)
        if not config:
            raise ValueError(f"Model {model.__name__} is not registered.")
        return config
