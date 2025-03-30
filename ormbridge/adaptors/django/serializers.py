import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Type

from django.conf import settings
from django.db import models
from django.utils.module_loading import import_string
from rest_framework import serializers
import contextvars
from contextlib import contextmanager
import logging

from ormbridge.adaptors.django.config import config, registry
from ormbridge.core.caching import CachingMixin
from ormbridge.core.classes import ModelSummaryRepresentation
from ormbridge.core.interfaces import AbstractDataSerializer, AbstractQueryOptimizer
from ormbridge.core.types import RequestType

logger = logging.getLogger(__name__)

# Create a thread-local storage for the fields_map
fields_map_var = contextvars.ContextVar('fields_map', default=None)

@contextmanager
def fields_map_context(fields_map):
    """
    Context manager that sets the fields_map for the current context.
    """
    # Save the previous value to restore it later
    token = fields_map_var.set(fields_map)
    try:
        yield
    finally:
        # Restore the previous value
        fields_map_var.reset(token)

def get_current_fields_map():
    """
    Get the fields_map from the current context.
    Returns an empty dict if no fields_map is set.
    """
    return fields_map_var.get() or {}

def get_custom_serializer(field_class: Type) -> Optional[Type[serializers.Field]]:
    """
    Look up a custom serializer override for a given model field.
    First, it checks the config registry, and then falls back to Django settings.
    """
    if field_class in config.custom_serializers:
        return config.custom_serializers[field_class]

    custom_serializers = getattr(settings, "CUSTOM_FIELD_SERIALIZERS", {})
    key = f"{field_class.__module__}.{field_class.__name__}"
    serializer_path = custom_serializers.get(key)
    if serializer_path:
        return import_string(serializer_path)
    return None
    
def extract_fields(model_name:str=None) -> Set[str]:
    """
    Extract the set of fields that should be included based on the fields_map and current path.
    
    Args:
        fields_map (dict): Dictionary mapping model names to sets of field names,
        model_name (str): Optional model name for model-based filtering
        
    Returns:
        set: Set of field names that should be included, or None if all fields should be included
    """
    return get_current_fields_map().get(model_name)

class DynamicModelSerializer(CachingMixin, serializers.ModelSerializer):
    """
    A dynamic serializer that adds two extra read-only fields ('repr' and 'img'),
    replaces relation fields with RelatedFieldWithRepr, and injects additional computed
    fields from the registry.
    """

    repr = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.depth = kwargs.pop("depth", 0)
        self.cache_backend = kwargs.pop("cache_backend", config.cache_backend)
        self.dependency_store = kwargs.pop("dependency_store", config.dependency_store)
        self.request = kwargs.pop("request", None)

        super().__init__(*args, **kwargs)

        # Get the model name
        model_name = config.orm_provider.get_model_name(self.Meta.model)
        pk_field = self.Meta.model._meta.pk.name

        # Use the extracted function to get the allowed fields
        allowed_fields = extract_fields(model_name=model_name)

        # Allowed fields must exist
        allowed_fields = allowed_fields or set()

        # Always include the primary key and the 'repr' field.
        allowed_fields.add(pk_field)
        allowed_fields.add("repr")
        
        # Filter the fields based on the result
        self.fields = {
            name: field for name, field in self.fields.items() 
            if name in allowed_fields
        }
    
    def get_repr(self, obj):
        """
        Returns a standard Repr of the model displayed in the model summary
        """
        pk_field = obj._meta.pk.name
        img_repr = obj.__img__() if hasattr(obj, "__img__") else None
        str_repr = str(obj)

        # Return directly the repr dict that the test expects
        return {
            "str": str_repr,
            "img": img_repr
        }

    def to_internal_value(self, data):
        # If this is being used as a related field (not the root serializer)
        if self.root != self:
            # If data is already a Django model instance, return it directly
            if hasattr(data, '_meta'):
                return data
                
            # Get the primary key field
            pk_field = self.Meta.model._meta.pk.name
            
            # Handle dictionary or primitive value
            pk = data.get(pk_field) if isinstance(data, dict) else data
            try:
                instance = self.Meta.model.objects.get(**{pk_field: pk})
                return instance
            except self.Meta.model.DoesNotExist:
                raise serializers.ValidationError({
                    pk_field: f"Related object with {pk_field} {pk} does not exist."
                })
        
        # Otherwise, use the standard deserialization
        return super().to_internal_value(data)
    
    def create(self, validated_data):
        """
        Override create method to handle nested relationships.
        Specifically extracts M2M relationships to set after instance creation.
        """
        many_to_many = {}
        for field_name, field in self.fields.items():
            if field_name in validated_data and isinstance(field, serializers.ListSerializer):
                many_to_many[field_name] = validated_data.pop(field_name)
        
        # Create the instance with the remaining data
        instance = super().create(validated_data)
        
        # Set many-to-many relationships after instance creation
        for field_name, value in many_to_many.items():
            field = getattr(instance, field_name)
            field.set(value)
        
        return instance

    def update(self, instance, validated_data):
        """
        Override update method to handle nested relationships.
        """
        many_to_many = {}
        for field_name, field in self.fields.items():
            if field_name in validated_data and isinstance(field, serializers.ListSerializer):
                many_to_many[field_name] = validated_data.pop(field_name)
        
        # Update the instance with the remaining data
        instance = super().update(instance, validated_data)
        
        # Update many-to-many relationships
        for field_name, value in many_to_many.items():
            field = getattr(instance, field_name)
            field.set(value)
        
        return instance

    def to_representation(self, instance):
        """
        Overridden to_representation that integrates caching directly.
        """
        model = self.Meta.model
        model_config = registry.get_config(model)

        # If cache_ttl is 0, caching is disabled for this model
        if model_config.cache_ttl == 0:
            return super().to_representation(instance)
        
        if self.cache_backend is not None:
            get_model_name = config.orm_provider.get_model_name
            cache_key = self.generate_cache_key(
                model, instance, self.depth, get_current_fields_map(), get_model_name
            )
            cached = self.get_cached_result(cache_key)
            if cached is not None:
                return cached
            
            # Get model name and allowed fields
            model_name = config.orm_provider.get_model_name(model)
            allowed_fields = extract_fields(model_name)

            # Register the instance itself as a dependency BEFORE serializing
            self.log_dependency(instance, get_model_name)

            # For ForeignKey fields, register those as dependencies too
            for field in model._meta.get_fields():
                # Skip fields that won't be presented
                if not allowed_fields:
                    break

                if field.name not in allowed_fields:
                    continue

                if (
                    field.is_relation
                    and field.concrete
                    and not getattr(field, "auto_created", False)
                ):
                    related_instance = getattr(instance, field.name, None)
                    if (
                        related_instance
                        and hasattr(related_instance, "pk")
                        and related_instance.pk
                    ):
                        self.log_dependency(related_instance, get_model_name)

            result = super().to_representation(instance)
                
            # Cache the result with the model-specific TTL
            self.cache_result(cache_key, result, model_config.cache_ttl)
            return result
        else:
            return super().to_representation(instance)

    class Meta:
        model = None  # To be set dynamically.
        fields = "__all__"
        
    @classmethod
    def _setup_relation_fields(cls, serializer_class, model, allowed_fields, depth):
        """Configure relation fields to use nested DynamicModelSerializer instances."""
        for field in model._meta.get_fields():
            if allowed_fields is None:
                break
            
            # Skip fields that won't be presented
            if field.name not in allowed_fields:
                continue
            
            if getattr(field, "auto_created", False) and not field.concrete:
                continue
                
            if field.is_relation:
                # Determine if this is a many-to-many or one-to-many field
                is_many = field.many_to_many or field.one_to_many
                
                # Create a serializer class for the related model
                nested_serializer_class = cls.for_model(
                    model=field.related_model, 
                    depth=max(depth - 1, -1)
                )
                
                # Set the nested serializer field
                serializer_class._declared_fields[field.name] = nested_serializer_class(
                    many=is_many,
                    read_only=False,
                    required=not (field.null or field.blank),
                    allow_null=field.null,
                    depth=max(depth - 1, -1)
                )
        return serializer_class
                
    @classmethod
    def _setup_custom_serializers(cls, serializer_class, model, allowed_fields):
        """Configure custom serializers for non-relation fields."""
        for field in model._meta.get_fields():
            # Skip fields that won't be presented
            if field.name not in allowed_fields:
                continue
            if getattr(field, "auto_created", False) and not field.concrete:
                continue
                
            if not field.is_relation:
                custom_field_serializer = get_custom_serializer(field.__class__)
                if custom_field_serializer:
                    serializer_class.serializer_field_mapping[field.__class__] = custom_field_serializer
        return serializer_class
        
    @classmethod
    def _setup_computed_fields(cls, serializer_class, model):
        """Set up additional computed fields from the model registry."""
        try:
            model_config = registry.get_config(model)
        except ValueError:
            return serializer_class  # No model config, return unchanged
            
        mapping = serializers.ModelSerializer.serializer_field_mapping
        
        for additional_field in model_config.additional_fields:
            drf_field_class = mapping.get(type(additional_field.field))
            if not drf_field_class:
                continue
                
            field_kwargs = {"read_only": True}
            if additional_field.title:
                field_kwargs["label"] = additional_field.title
                
            # Pass along required attributes based on field type.
            if isinstance(additional_field.field, models.DecimalField):
                field_kwargs["max_digits"] = additional_field.field.max_digits
                field_kwargs["decimal_places"] = additional_field.field.decimal_places
            elif isinstance(additional_field.field, models.CharField):
                field_kwargs["max_length"] = additional_field.field.max_length
                
            # Instantiate the serializer field.
            serializer_field = drf_field_class(**field_kwargs)
            serializer_field.source = additional_field.name
            serializer_class._declared_fields[additional_field.name] = serializer_field
            
        return serializer_class

    @classmethod
    def for_model(cls, model: Type[models.Model], depth: int = 0):
        """
        Create a DynamicModelSerializer class for the given model with the specified depth.
        This configures all serialization behavior including:
        - Setting up the Meta class
        - Configuring list serialization
        - Setting up relation fields
        - Registering custom serializers
        - Adding computed fields from the registry
        """
        pk_field = model._meta.pk.name
            
        # Dynamically create a Meta inner class
        Meta = type("Meta", (), {
            "model": model, 
            "fields": "__all__", 
            "read_only_fields": (pk_field,)
        })
        
        # Create the serializer class
        serializer_class = type(
            f"Dynamic{model.__name__}Serializer", 
            (cls,), 
            {"Meta": Meta}
        )
        
        # Get allowed fields for this model
        model_name = config.orm_provider.get_model_name(model)
        allowed_fields = extract_fields(model_name)
        
        # Only proceed with field setup if we have allowed fields
        if allowed_fields and depth >= 0:
            # Set up relation fields with RelatedFieldWithRepr
            serializer_class = cls._setup_relation_fields(
                serializer_class, model, allowed_fields, depth
            )
            
            # Register custom serializers for model fields
            serializer_class = cls._setup_custom_serializers(
                serializer_class, model, allowed_fields
            )
        
            # Add computed fields from the registry
            serializer_class = cls._setup_computed_fields(serializer_class, model)
        
        return serializer_class

class DRFDynamicSerializer(AbstractDataSerializer):
    """
    The abstract base class for DRF serialization.

    In this design, the private `_serialize` method instantiates a DynamicModelSerializer
    with a fields_map set at the class level. This ensures all dependencies are properly
    collected throughout the serialization chain.
    """

    def _optimize_queryset(self, data, model, depth, fields_map):
        if isinstance(data, models.QuerySet) and config.query_optimizer is not None:
            try:
                query_optimizer: Type[AbstractQueryOptimizer] = config.query_optimizer(
                    depth=depth,
                    fields_per_model=fields_map,
                    get_model_name_func=config.orm_provider.get_model_name,
                )
                
                # Common kwargs for both optimization paths
                optimization_kwargs = {
                    'depth': depth,
                    'fields_map': fields_map,
                    'get_model_name_func': config.orm_provider.get_model_by_name
                }
                
                if "requested-fields::" in fields_map:
                    requested_fields = fields_map["requested-fields::"]
                    data = query_optimizer.optimize(
                        queryset=data,
                        fields=requested_fields,
                        **optimization_kwargs
                    )
                    logger.debug(f"Query optimized for {model.__name__} with fields: {requested_fields}")
                else:
                    data = query_optimizer.optimize(
                        queryset=data,
                        **optimization_kwargs
                    )
                    logger.debug(f"Query optimized for {model.__name__} with no explicit field selection")
            except Exception as e:
                logger.error(f"Error optimizing query for {model.__name__}: {e}")
        
        return data  # Make sure to return data regardless of optimization

    def _serialize(
        self,
        data: Any,
        model: Type[models.Model],
        depth: int,
        fields_map: Dict[str, Set[str]],
        many: bool,
        request: Optional[RequestType] = None
    ) -> DynamicModelSerializer:
        # Serious security issue if fields_map is None
        assert fields_map is not None, "fields_map is required and cannot be None"

        data = self._optimize_queryset(
            data= data,
            model= model,
            depth= depth,
            fields_map=fields_map
        )
        
        # Create the serializer class with fields_map as a class attribute
        serializer_class = DynamicModelSerializer.for_model(
            model=model, 
            depth=depth
        )
        
        # Pass explicit parameters without fields_map
        serializer = serializer_class(
            data,
            many=many,
            depth=depth,
            cache_backend=config.cache_backend,
            dependency_store=config.dependency_store,
            request=request
        )

        return serializer

    def serialize(
        self,
        data: Any,
        model: Type[models.Model],
        depth: int,
        fields_map: Optional[Dict[str, Set[str]]],
        many: bool = False,
        request: Optional[RequestType] = None
    ) -> Any:
        """
        Public serialization method.
        Instantiates the serializer via `_serialize` and then returns its cached data.
        With the shared dependency registry, the top-level cache key will be associated
        with all nested dependencies (e.g. reservation depends on home, address, postcode),
        while a nested serializer (e.g. home) registers only its own nested dependencies.
        """

        # Serious security issue if fields_map is None
        assert fields_map is not None, "fields_map is required and cannot be None"
        
        with fields_map_context(fields_map):
            serializer = self._serialize(
                data=data, 
                model=model,
                depth=depth,
                fields_map=fields_map, 
                many=many, 
                request=request
            )
            return serializer.data

    def deserialize(
        self,
        model: Type[models.Model],
        data: Dict[str, Any],
        fields_map: Optional[Dict[str, Set[str]]],
        partial: bool = False,
        request: Optional[RequestType] = None,
    ) -> Dict[str, Any]:
        # Serious security issue if fields_map is None
        assert fields_map is not None, "fields_map is required and cannot be None"

        # Use the context manager for the duration of deserialization
        with fields_map_context(fields_map):
            # Create serializer class
            serializer_class = DynamicModelSerializer.for_model(
                model=model, 
                depth=0
            )

            model_config = registry.get_config(model)

            if model_config.pre_hooks:
                for hook in model_config.pre_hooks:
                    data = hook(data, request=request)

            # Create serializer
            serializer = serializer_class(
                data=data, 
                partial=partial,
                request=request
            )
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            if model_config.post_hooks:
                for hook in model_config.post_hooks:
                    validated_data = hook(validated_data, request=request)
            return validated_data
    
    def save(
        self, 
        model: Type[models.Model], 
        data: Dict[str, Any],
        fields_map: Optional[Dict[str, Set[str]]],
        instance: Optional[Any] = None,
        partial: bool = True,
        request: Optional[RequestType] = None
    ) -> Any:
        """
        Save data to create a new instance or update an existing one. Note that this does no field level
        validation so its ESSENTIAL that deserialize is already called on the data / instance before it is
        provided to the save method.
        
        Args:
            model: The model class
            data: Data to save
            instance: Optional existing instance to update (if None, creates new instance)
            fields_map: Optional mapping of field restrictions
            partial: Whether this is a partial update (default True, only relevant for updates)
            
        Returns:
            The saved instance (either created or updated)
        """
        # Serious security issue if fields_map is None
        assert fields_map is not None, "fields_map is required and cannot be None"

        # Get all fields using the ORM provider
        all_fields = config.orm_provider.get_fields(model)
        model_name = config.orm_provider.get_model_name(model)

        # Create an unrestricted fields map
        unrestricted_fields_map = {model_name: all_fields}
        
        # Use the context manager with the unrestricted fields map
        with fields_map_context(unrestricted_fields_map):
            # Create serializer class
            serializer_class = DynamicModelSerializer.for_model(
                model=model, 
                depth=0  # No need for depth during save
            )
            
            # Create serializer
            serializer = serializer_class(
                instance=instance,  # Will be None for creation
                data=data,
                partial=partial if instance else False,  # partial only makes sense for updates
                request=request
            )
            
            # Validate the data
            serializer.is_valid(raise_exception=True)
            
            # Save and return the instance
            return serializer.save()