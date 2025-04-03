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
from zen_queries import queries_disabled

from statezero.adaptors.django.config import config, registry
from statezero.core.classes import ModelSummaryRepresentation
from statezero.core.interfaces import AbstractDataSerializer, AbstractQueryOptimizer
from statezero.core.types import RequestType

logger = logging.getLogger(__name__)

# Create a thread-local storage for the fields_map
fields_map_var = contextvars.ContextVar('fields_map', default=None)

# Add a new context variable for normalized output
normalized_output_var = contextvars.ContextVar('normalized_output', default={})
model_registry_var = contextvars.ContextVar('model_registry', default={})

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

@contextmanager
def normalized_output_context():
    """
    Context manager that provides a fresh normalized output dictionary.
    """
    # Initialize empty containers for the normalized output
    normalized_map = {}
    model_registry = {}
    
    # Set the context variables
    output_token = normalized_output_var.set(normalized_map)
    registry_token = model_registry_var.set(model_registry)
    
    try:
        yield normalized_map
    finally:
        # Restore the previous values
        normalized_output_var.reset(output_token)
        model_registry_var.reset(registry_token)

def get_current_fields_map():
    """
    Get the fields_map from the current context.
    Returns an empty dict if no fields_map is set.
    """
    return fields_map_var.get() or {}

def get_current_normalized_output():
    """
    Get the normalized output dictionary from the current context.
    """
    return normalized_output_var.get()

def get_current_model_registry():
    """
    Get the model registry from the current context.
    """
    return model_registry_var.get()

def register_normalized_entity(model_type, model_id, data):
    """
    Register a normalized entity in the output map.
    
    Args:
        model_type (str): The type/name of the model
        model_id: The ID of the entity
        data (dict): The serialized data
    
    Returns:
        dict: A reference object with type and id
    """
    normalized_output = get_current_normalized_output()
    model_registry = get_current_model_registry()
    
    # Create the entity key
    entity_key = f"{model_type}"
    if entity_key not in normalized_output:
        normalized_output[entity_key] = {}
    
    # Store the entity data
    normalized_output[entity_key][str(model_id)] = data
    
    # Create a reference object
    ref_object = {
        "type": model_type,
        "id": model_id
    }
    
    # Register in the model registry to avoid duplicate processing
    registry_key = f"{model_type}:{model_id}"
    model_registry[registry_key] = True
    
    return ref_object

def is_entity_registered(model_type, model_id):
    """
    Check if an entity is already registered in the current context.
    
    Args:
        model_type (str): The type/name of the model
        model_id: The ID of the entity
        
    Returns:
        bool: True if the entity is already registered
    """
    model_registry = get_current_model_registry()
    registry_key = f"{model_type}:{model_id}"
    return registry_key in model_registry

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

class DynamicModelSerializer(serializers.ModelSerializer):
    """
    A dynamic serializer that adds two extra read-only fields ('repr' and 'img'),
    replaces relation fields with RelatedFieldWithRepr, and injects additional computed
    fields from the registry.
    """

    repr = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.depth = kwargs.pop("depth", 0)
        self.request = kwargs.pop("request", None)
        self.normalize_output = kwargs.pop("normalize_output", True)

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
        Overridden to_representation that integrates normalization.
        """
        model = self.Meta.model
        model_name = config.orm_provider.get_model_name(model)
        pk_field = model._meta.pk.name
        model_id = getattr(instance, pk_field)
        
        # Check if normalization is enabled and this instance has already been registered
        if self.normalize_output and is_entity_registered(model_name, model_id):
            # Return just a reference to the already normalized entity
            return {
                "type": model_name,
                "id": model_id
            }
        
        # Get standard representation
        result = super().to_representation(instance)
        
        # Register this entity if normalization is enabled
        if self.normalize_output:
            # If this is the root serializer, we'll handle the final output in the serialize method
            if self.root == self:
                # For nested serializers, we need to register the entity
                register_normalized_entity(model_name, model_id, result)
            else:
                # Register the entity and return a reference to it
                return register_normalized_entity(model_name, model_id, result)
                
        return result

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
        if config.query_optimizer is None:
            return data
        if isinstance(data, models.QuerySet) or isinstance(data, model):
            try:
                query_optimizer: Type[AbstractQueryOptimizer] = config.query_optimizer(
                    depth=depth,
                    fields_per_model=fields_map,
                    get_model_name_func=config.orm_provider.get_model_name,
                )
                
                if "requested-fields::" in fields_map:
                    requested_fields = fields_map["requested-fields::"]
                    data = query_optimizer.optimize(
                        queryset=data,
                        fields=requested_fields
                    )
                    logger.debug(f"Query optimized for {model.__name__} with fields: {requested_fields}")
                else:
                    data = query_optimizer.optimize(
                        queryset=data
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
        normalize_output: bool = True,
        request: Optional[RequestType] = None
    ) -> DynamicModelSerializer:
        # Serious security issue if fields_map is None
        assert fields_map is not None, "fields_map is required and cannot be None"
        
        data = self._optimize_queryset(
            data=data,
            model=model,
            depth=depth,
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
            normalize_output=normalize_output,
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
        For reads, returns a flattened normalized structure.
        """
        # Serious security issue if fields_map is None
        assert fields_map is not None, "fields_map is required and cannot be None"
        
        with fields_map_context(fields_map):
            # Set up the normalized output context
            with normalized_output_context() as normalized_map:
                serializer = self._serialize(
                    data=data, 
                    model=model,
                    depth=depth,
                    fields_map=fields_map, 
                    many=many,
                    request=request
                )

                # Apply zen-queries protection only to the data access part
                if getattr(settings, 'ZEN_STRICT_SERIALIZATION', False):
                    with queries_disabled():
                        # This will raise an exception if any query is executed
                        serialized_data = serializer.data
                else:
                    # Original code path without zen-queries
                    serialized_data = serializer.data
                
                # If it's a single object, register it in the normalized map if not already there
                if not many and serialized_data:
                    model_name = config.orm_provider.get_model_name(model)
                    pk_field = model._meta.pk.name
                    
                    # Check if the object is already in the normalized map
                    if not is_entity_registered(model_name, serialized_data.get(pk_field)):
                        instance = data
                        register_normalized_entity(
                            model_name,
                            getattr(instance, pk_field),
                            serialized_data
                        )
                
                # Return the normalized output with a reference to the root data
                return {
                    "data": serialized_data,
                    "included": normalized_map
                }

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

            # Create serializer (with normalization disabled for write operations)
            serializer = serializer_class(
                data=data, 
                partial=partial,
                normalize_output=False,
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
        Save data to create a new instance or update an existing one.
        This is unchanged from the original implementation.
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
            
            # Create serializer (with normalization disabled for write operations)
            serializer = serializer_class(
                instance=instance,  # Will be None for creation
                data=data,
                normalize_output=False,
                partial=partial if instance else False,  # partial only makes sense for updates
                request=request
            )
            
            # Validate the data
            serializer.is_valid(raise_exception=True)
            
            # Save and return the instance
            return serializer.save()