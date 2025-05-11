from typing import Any, Dict, List, Optional, Set, Type, Union
from django.db import models
from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework import serializers
import contextvars
from contextlib import contextmanager
import logging
from cytoolz import pluck
from zen_queries import queries_disabled

from statezero.adaptors.django.config import config, registry
from statezero.core.interfaces import AbstractDataSerializer, AbstractQueryOptimizer
from statezero.core.types import RequestType
from statezero.adaptors.django.helpers import collect_from_queryset

logger = logging.getLogger(__name__)

# Context variables remain the same
fields_map_var = contextvars.ContextVar('fields_map', default=None)

@contextmanager
def fields_map_context(fields_map):
    """
    Context manager that sets the fields_map for the current context.
    """
    token = fields_map_var.set(fields_map)
    try:
        yield
    finally:
        fields_map_var.reset(token)

def get_current_fields_map():
    """
    Get the fields_map from the current context.
    Returns an empty dict if no fields_map is set.
    """
    return fields_map_var.get() or {}

def extract_fields(model_name:str=None) -> Set[str]:
    """
    Extract the set of fields that should be included based on the fields_map and current path.
    
    Args:
        model_name (str): Optional model name for model-based filtering
        
    Returns:
        set: Set of field names that should be included, or None if all fields should be included
    """
    return get_current_fields_map().get(model_name)

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

class FlexiblePrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """
    A custom PrimaryKeyRelatedField that can handle both primary keys and model instances.
    """
    def to_internal_value(self, data):
        # If data is already a model instance, extract its primary key
        if hasattr(data, '_meta'):
            pk_field = data._meta.pk.name
            pk_value = getattr(data, pk_field)
            return super().to_internal_value(pk_value)
        
        # If data is a dictionary with a key matching the PK field name, extract the value
        if isinstance(data, dict) and self.queryset.model._meta.pk.name in data:
            pk_value = data[self.queryset.model._meta.pk.name]
            return super().to_internal_value(pk_value)
        
        # Otherwise, use the standard to_internal_value
        return super().to_internal_value(data)
    
class FExpressionMixin:
    """
    A mixin that can handle F expression objects in serializer write operations.
    """
    def to_internal_value(self, data):
        """
        Override to_internal_value to handle F expressions before standard validation.
        """
        # Check if data is a dictionary, if not let the parent handle it
        if not isinstance(data, dict):
            return super().to_internal_value(data)
            
        # First extract F expressions
        f_expressions = {}
        data_copy = {**data}  # Create a copy to modify
        
        for field_name, value in data.items():
            if isinstance(value, dict) and value.get('__f_expr'):
                # Store F expressions for later
                f_expressions[field_name] = value
                # Remove them from the data to avoid validation errors
                data_copy.pop(field_name)
        
        # Standard validation for remaining fields
        validated_data = super().to_internal_value(data_copy)
        
        # Add F expressions back to the validated data
        for field_name, value in f_expressions.items():
            validated_data[field_name] = value
            
        return validated_data

class DynamicModelSerializer(FExpressionMixin, serializers.ModelSerializer):
    """
    A dynamic serializer that adds a read-only 'repr' field
    and applies custom serializers for model fields.
    """
    repr = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.get_model_name = kwargs.pop("get_model_name", config.orm_provider.get_model_name)
        self.depth = kwargs.pop("depth", 0)  # Always 0
        self.request = kwargs.pop("request", None)
        
        super().__init__(*args, **kwargs)

        # Get the model name
        model_name = config.orm_provider.get_model_name(self.Meta.model)
        pk_field = self.Meta.model._meta.pk.name

        # Use the extracted function to get the allowed fields
        allowed_fields = extract_fields(model_name=model_name)

        # Allowed fields must exist
        allowed_fields = allowed_fields or set()

        # Always include the primary key and the 'repr' field
        allowed_fields.add(pk_field)
        allowed_fields.add("repr")
        
        # Filter the fields based on the result
        if allowed_fields:
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

        return {
            "str": str_repr,
            "img": img_repr
        }
    
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

    class Meta:
        model = None  # To be set dynamically.
        fields = "__all__"

    
    @classmethod
    def _setup_relation_fields(cls, serializer_class, model, allowed_fields):
        """Configure relation fields to use PrimaryKeyRelatedField."""
        allowed_fields = allowed_fields or set()
        
        for field in model._meta.get_fields():
            # Skip fields that won't be presented
            if field.name not in allowed_fields:
                continue
                
            if getattr(field, "auto_created", False) and not field.concrete:
                continue
                
            if field.is_relation:
                queryset = field.related_model.objects.all()
                serializer_class._declared_fields[field.name] = FlexiblePrimaryKeyRelatedField(
                    queryset=queryset,
                    required=not (field.null or field.blank),
                    allow_null=field.null,
                    many= field.many_to_many or field.one_to_many
                )
                    
        return serializer_class
                
    @classmethod
    def _setup_custom_serializers(cls, serializer_class, model, allowed_fields):
        """Configure custom serializers for non-relation fields."""
        allowed_fields = allowed_fields or set()
        
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
    def _setup_computed_fields(cls, serializer_class, model, allowed_fields):
        """Set up additional computed fields from the model registry."""
        try:
            model_config = registry.get_config(model)
        except ValueError:
            return serializer_class  # No model config, return unchanged
            
        mapping = serializers.ModelSerializer.serializer_field_mapping
        
        for additional_field in model_config.additional_fields:
            if additional_field.name not in allowed_fields:
                continue
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
    def for_model(cls, model: Type[models.Model]):
        """
        Create a DynamicModelSerializer class for the given model.
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
        if allowed_fields:
            # Register custom serializers for model fields
            serializer_class = cls._setup_custom_serializers(
                serializer_class, model, allowed_fields
            )
        
            # Add computed fields from the registry
            serializer_class = cls._setup_computed_fields(serializer_class, model, allowed_fields)
            # Add relationship fields
            serializer_class = cls._setup_relation_fields(serializer_class, model, allowed_fields)
        
        return serializer_class

class DRFDynamicSerializer(AbstractDataSerializer):
    """
    Uses collect_from_queryset to gather model instances
    and applies DynamicModelSerializer for each group of models.
    """

    def _optimize_queryset(self, data, model, fields_map):
        if config.query_optimizer is None:
            return data
        if isinstance(data, models.QuerySet) or isinstance(data, model):
            try:
                query_optimizer: Type[AbstractQueryOptimizer] = config.query_optimizer(
                    depth=0,  # Always use depth 0 since we're collecting models explicitly
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
        
        return data

    def serialize(
        self,
        data: Any,
        model: Type[models.Model],
        depth: int,  # Parameter kept for API compatibility, but no longer used
        fields_map: Optional[Dict[str, Set[str]]],
        many: bool = False,
        request: Optional[RequestType] = None
    ) -> Any:
        """
        Serializes data using collect_from_queryset and applies DynamicModelSerializer
        for each group of models.
        
        Returns a format of:
        {
            "data": [pks], # list of primary keys for top-level models
            "included": {
                "modelName": [objects], # full serialized objects per model type
            }
        }
        """
        # Validate fields_map
        assert fields_map is not None, "fields_map is required and cannot be None"
        
        # Handle None data
        if data is None:
            return {
                "data": [],
                "included": {},
                "model_name": None
            }
        
        # Apply query optimization
        data = self._optimize_queryset(data, model, fields_map)
        
        # Use the fields_map context for all operations
        with fields_map_context(fields_map):
            # Collect all model instances based on the fields_map
            collected_models = collect_from_queryset(
                data=data,
                fields_map=fields_map,
                get_model_name=config.orm_provider.get_model_name,
                get_model=config.orm_provider.get_model_by_name
            )
            
            # Extract primary keys for the top-level model
            model_name = config.orm_provider.get_model_name(model)
            pk_field = model._meta.pk.name
            top_level_instances = []

            # Initialize the response structure
            result = {
                "data": [],
                "included": {},
                "model_name": model_name
            }
            
            # For QuerySets, gather all instances
            if isinstance(data, models.QuerySet):
                top_level_instances = list(data)
            # For single instance
            elif isinstance(data, model):
                top_level_instances = [data]
            # For many=True with a list of instances
            elif many and isinstance(data, list):
                top_level_instances = [item for item in data if isinstance(item, model)]
            
            # Extract primary keys for top-level instances
            result["data"] = [getattr(instance, pk_field) for instance in top_level_instances]
            
            # Apply zen-queries protection if configured
            query_protection = getattr(settings, 'ZEN_STRICT_SERIALIZATION', False)
            
            # Serialize each group of models
            for model_type, instances in collected_models.items():
                # Skip empty collections
                if not instances:
                    continue
                
                try:
                    # Get the model class for this type
                    model_class = config.orm_provider.get_model_by_name(model_type)
                    
                    # Create a serializer for this model type
                    serializer_class = DynamicModelSerializer.for_model(model_class)
                    
                    # Apply zen-queries protection if configured
                    if query_protection:
                        with queries_disabled():
                            # This will raise an exception if any query is executed
                            serialized_data = serializer_class(instances, many=True).data
                    else:
                        # Original code path without zen-queries
                        serialized_data = serializer_class(instances, many=True).data

                    pk_field_name = model_class._meta.pk.name
                    # [{pk: 1, ...}, {pk: 2, ...}] -> {1: {...}, 2: {...}}
                    # Create a dictionary indexed by primary key for easy lookup in the frontend
                    pk_indexed_data = dict(zip(pluck(pk_field_name, serialized_data), serialized_data))
                    
                    # Add the serialized data to the result
                    result["included"][model_type] = pk_indexed_data
                    
                except Exception as e:
                    logger.error(f"Error serializing {model_type}: {e}")
                    # Include an empty list for this model type to maintain the expected structure
                    result["included"][model_type] = {}
            
            return result

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
            serializer_class = DynamicModelSerializer.for_model(model)

            try:
                model_config = registry.get_config(model)
                if model_config.pre_hooks:
                    for hook in model_config.pre_hooks:
                        data = hook(data, request=request)
            except ValueError:
                # No model config available
                model_config = None

            # Create serializer
            serializer = serializer_class(
                data=data, 
                partial=partial,
                request=request
            )
            serializer.is_valid(raise_exception=True)
            validated_data = serializer.validated_data

            if model_config and model_config.post_hooks:
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
            serializer_class = DynamicModelSerializer.for_model(model)
            
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