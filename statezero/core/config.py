from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union, Literal
import networkx as nx
import warnings


from statezero.core.classes import AdditionalField
from statezero.core.event_bus import EventBus
from statezero.core.interfaces import (AbstractCustomQueryset,
                                       AbstractDataSerializer,
                                       AbstractORMProvider, AbstractPermission,
                                       AbstractSchemaGenerator, AbstractSearchProvider, AbstractQueryOptimizer)
from statezero.core.types import ORMField

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
    default_limit: Optional[int] = None
    orm_provider: AbstractORMProvider = None
    search_provider: AbstractSearchProvider = None

    # Query optimizers
    query_optimizer: Optional[AbstractQueryOptimizer] = None
    file_upload_callbacks: Optional[List[str]] = None

    # Telemetry for debugging
    enable_telemetry: bool = False

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

    def validate_exposed_models(self, registry: Registry) -> bool:
        """
        Validate that all registered models only expose fields 
        that reference other registered models.
        
        This implementation is ORM-agnostic, using the configured orm_provider
        to access model relationships.
        
        Args:
            registry: The global registry containing registered models
            
        Returns:
            bool: True if validation passes
            
        Raises:
            ValueError: If a registered model exposes an unregistered model
        """
        if not self.orm_provider:
            raise ValueError("ORM provider must be initialized before validation")
            
        # Build complete model graph for all registered models
        model_graph = nx.DiGraph()
        for model in registry._models_config.keys():
            model_graph = self.orm_provider.build_model_graph(model, model_graph)
            
        # Check each registered model
        for model, config in registry._models_config.items():
            # Get model name for error messages and graph lookup
            model_name = self.orm_provider.get_model_name(model)
            
            # Get all field nodes from the graph for this model
            all_model_fields = set()
            for _, field_node in model_graph.out_edges(model_name):
                if "::" in field_node:
                    field_name = field_node.split("::")[-1]
                    all_model_fields.add(field_name)
                    
            # Determine which fields to check based on config.fields
            fields_to_check = config.fields if config.fields != "__all__" else all_model_fields
            
            # Check each field to see if it's a relation to an unregistered model
            for field_name in fields_to_check:
                field_node = f"{model_name}::{field_name}"
                
                if model_graph.has_node(field_node):
                    node_data = model_graph.nodes[field_node].get("data")
                    if node_data and node_data.is_relation:
                        related_model_name = node_data.related_model
                        if related_model_name:
                            # Get the related model from its name
                            related_model = self.orm_provider.get_model_by_name(related_model_name)
                            
                            # Check if related model is registered
                            if related_model not in registry._models_config:
                                raise ValueError(
                                    f"Model '{model_name}' exposes relation '{field_name}' "
                                    f"to unregistered model '{related_model_name}'. "
                                    f"Please register '{related_model_name}' with StateZero "
                                    f"or restrict access to this field by excluding it from the 'fields' parameter."
                                )
                                
        return True


class ModelConfig:
    """
    Initialize model-specific configuration.

    Parameters:
    -----------
    model: Type
        The model class to register
    permissions: List[Type[AbstractPermission]], optional
        Permission classes that control access to this model
    pre_hooks: List[Callable], optional
        Functions to run before serialization/deserialization
    post_hooks: List[Callable], optional
        Functions to run after serialization/deserialization
    additional_fields: List[AdditionalField], optional
        Additional computed fields to add to the model schema
    filterable_fields: Optional[Union[Set[str], Literal["__all__"]]], optional
        Fields that can be used in filter queries
    searchable_fields: Optional[Union[Set[str], Literal["__all__"]]], optional
        Fields that can be used in search queries
    ordering_fields: Optional[Union[Set[str], Literal["__all__"]]], optional
        Fields that can be used for ordering
    fields: Optional[Optional[Union[Set[str], Literal["__all__"]]]]
        Expose just a subset of the model fields
    display: Optional[Any], optional
        Display metadata for frontend customization (DisplayMetadata instance)
    DEBUG: bool, default=False
        Enable debug mode for this model
    """

    def __init__(
        self,
        model: Type,
        permissions: Optional[List[Type[AbstractPermission]]] = None,
        pre_hooks: Optional[List] = None,
        post_hooks: Optional[List] = None,
        additional_fields: Optional[List[AdditionalField]] = None,
        filterable_fields: Optional[Union[Set[str], Literal["__all__"]]] = None,
        searchable_fields: Optional[Union[Set[str], Literal["__all__"]]] = None,
        ordering_fields: Optional[Union[Set[str], Literal["__all__"]]] = None,
        fields: Optional[Union[Set[str], Literal["__all__"]]] = None,
        display: Optional[Any] = None,
        DEBUG: bool = False,
    ):
        self.model = model
        self._permissions = permissions or []
        self.pre_hooks = pre_hooks or []
        self.post_hooks = post_hooks or []
        self.additional_fields = additional_fields or []
        self.filterable_fields = filterable_fields or set()
        self.searchable_fields = searchable_fields or set()
        self.ordering_fields = ordering_fields or set()
        self.fields = fields or "__all__"
        self.display = display
        self.DEBUG = DEBUG or False

        # Warn about additional fields that won't be included when fields is not __all__
        if self.DEBUG and self.additional_fields and self.fields != "__all__":
            additional_field_names = {af.name for af in self.additional_fields}
            fields_set = self.fields if isinstance(self.fields, set) else set(self.fields)
            missing_fields = additional_field_names - fields_set
            if missing_fields:
                warnings.warn(
                    f"Model '{model.__name__}': additional_fields {missing_fields} are declared but "
                    f"will be ignored because they are not included in the 'fields' list. "
                    f"To fix this, either add them to 'fields' or remove them from 'additional_fields'.",
                    UserWarning,
                    stacklevel=2
                )

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
