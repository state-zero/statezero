import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Type

from django.conf import settings
from django.db import models
from django.utils.module_loading import import_string
from rest_framework import serializers

from ormbridge.adaptors.django.config import config, registry
from ormbridge.core.caching import CachingMixin
from ormbridge.core.classes import ModelSummaryRepresentation

from ormbridge.core.interfaces import AbstractDataSerializer
from ormbridge.core.types import RequestType


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

class RelatedFieldWithRepr(serializers.RelatedField):
    """
    A custom related field that returns:
      - A minimal representation (primary key, repr, img, model_name) when depth == 0.
      - An expanded representation (via a nested DynamicModelSerializer) when depth > 0.

    For expanded representations, it calls `log_dependency` on the parent serializer.
    """

    def __init__(self, *args, **kwargs):
        self.depth = kwargs.pop("depth", 0)
        self.fields_map = kwargs.pop("fields_map", {})
        self.current_path = kwargs.pop("current_path", "")
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        model_name = config.orm_provider.get_model_name(value.__class__)
        
        # If field_name is None, this might be a nested instance of serialization
        field_name = getattr(self, 'field_name', None) or ""
        
        # Build the new current path
        new_path = f"{self.current_path}__{field_name}" if self.current_path else field_name
        
        # Use the extracted function to determine if we should expand
        allowed_fields = extract_fields(
            fields_map=self.fields_map,
            current_path=new_path,
            model_name=model_name
        )
        
        if allowed_fields:
            return self._expanded_representation(value, new_path)
        else:
            return self._minimal_representation(value)


    def _minimal_representation(self, instance):
        # Determine the primary key field from the model class (default to "id" if not provided)
        pk_field = instance._meta.pk.name
        img_repr = instance.__img__() if hasattr(instance, "__img__") else None
        str_repr = str(instance)

        rep = ModelSummaryRepresentation(
            pk=getattr(instance, pk_field),
            repr={"str": str_repr, "img": img_repr},
            model_name=instance.__class__.__name__,
            pk_field=pk_field,
        )
        return rep.to_dict()

    def _expanded_representation(self, instance, current_path):
        # Get the nearest parent serializer that implements log_dependency
        serializer_parent = self.parent
        if not hasattr(serializer_parent, "log_dependency") and hasattr(serializer_parent, "parent"):
            serializer_parent = serializer_parent.parent
        serializer_parent.log_dependency(instance, config.orm_provider.get_model_name)
        
        # Create serializer class with current_path
        serializer_class = DynamicModelSerializer.for_model(
            instance.__class__, 
            depth=self.depth - 1,
            fields_map=self.fields_map
        )
        
        # Create serializer instance with current_path
        serializer = serializer_class(
            instance,
            depth=self.depth - 1,
            current_path=current_path
        )
        
        # Use the nested serializer's own caching mechanism
        return serializer.cached_data()

    def to_internal_value(self, data):
        # If data is already a Django model instance, return it directly
        if hasattr(data, '_meta'):  # This is how we can check if it's a Django model
            return data
            
        # Use the model's actual pk field name  
        pk_field = getattr(
            self.queryset.model, "primaryKeyField", self.queryset.model._meta.pk.name
        )
        
        # Handle dictionary or primitive value
        pk = data.get(pk_field) if isinstance(data, dict) else data
        try:
            instance = self.queryset.get(**{pk_field: pk})
        except self.queryset.model.DoesNotExist:
            raise serializers.ValidationError(
                {pk_field: f"Related object with {pk_field} {pk} does not exist."}
            )
        return instance
    
class IndividualCachingListSerializer(serializers.ListSerializer):
    """
    A custom ListSerializer that caches individual instance representations.
    Instead of caching the entire list as one unit, it instantiates the child serializer
    for each instance and calls its cached_data() method.
    """

    def to_representation(self, data):
        result: List[Any] = []
        # For each instance, create a new serializer instance and use its caching.
        for item in data:
            # Get current path from the child serializer
            current_path = getattr(self.child, 'current_path', "")
            
            # Create the serializer without explicitly passing fields_map since it's at the class level
            serializer_instance = self.child.__class__(
                instance=item, 
                depth=getattr(self.child, 'depth', 0),
                current_path=current_path
            )
            result.append(serializer_instance.cached_data())
        return result

    def cached_data(self) -> Any:
        """
        Return the cached representation for the list by iterating over each instance.
        """
        return self.to_representation(self.instance)
    
def extract_fields(fields_map: Dict[str, Set[str]], current_path:str="", model_name:str=None):
    """
    Extract the set of fields that should be included based on the fields_map and current path.
    
    Args:
        fields_map (dict): Dictionary mapping model names to sets of field names,
                          or 'fields::' to a set of field paths
        current_path (str): Current path in the nested structure (e.g. "home__address")
        model_name (str): Optional model name for model-based filtering
        
    Returns:
        set: Set of field names that should be included, or None if all fields should be included
    """
    # Check if we have path-based filtering
    if 'fields::' in fields_map:
        direct_fields = set()
        
        prefix = current_path + "__" if current_path else ""
        
        for path in fields_map['fields::']:
            # If the path starts with our prefix
            if path.startswith(prefix):
                # Remove the prefix and get the first segment
                remaining = path[len(prefix):]
                if remaining:
                    field = remaining.split("__")[0]
                    direct_fields.add(field)
        
        # Return direct fields if we found any
        if direct_fields:
            return direct_fields
    
    # Fall back to standard model-based filtering
    if 'fields::' not in fields_map:
        return fields_map.get(model_name)
    
    # If no filtering was specified, return None
    return None

class DynamicModelSerializer(CachingMixin, serializers.ModelSerializer):
    """
    A dynamic serializer that adds two extra read-only fields ('repr' and 'img'),
    replaces relation fields with RelatedFieldWithRepr, and injects additional computed
    fields from the registry.

    Fields are filtered based on a provided fields_map.
    """

    repr = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.depth = kwargs.pop("depth", 0)
        self.current_path = kwargs.pop("current_path", "")
        self.cache_backend = kwargs.pop("cache_backend", config.cache_backend)
        self.dependency_store = kwargs.pop("dependency_store", config.dependency_store)
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        # Get the model name
        model_name = config.orm_provider.get_model_name(self.Meta.model)
        pk_field = self.Meta.model._meta.pk.name
        
        # Use the extracted function to get the allowed fields
        allowed_fields = extract_fields(
            fields_map=self.fields_map,
            current_path=self.current_path,
            model_name=model_name
        )

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

    def get_repr(self, obj) -> Dict[str, Optional[str]]:
        str_repr = str(obj)
        img_repr = obj.__img__() if hasattr(obj, "__img__") else None
        return {"str": str_repr, "img": img_repr}

    class Meta:
        model = None  # To be set dynamically.
        fields = "__all__"

    @classmethod
    def for_model(cls, model: Type[models.Model], depth: int = 0, fields_map: Optional[Dict[str, Set[str]]] = None):
        # Ensure we have a fields_map, even if empty
        if fields_map is None:
            fields_map = {}

        pk_field = model._meta.pk.name
            
        # Dynamically create a Meta inner class.
        Meta = type("Meta", (), {"model": model, "fields": "__all__", "read_only_fields": (pk_field,) })
        serializer_class = type(
            f"Dynamic{model.__name__}Serializer", 
            (cls,), 
            {
                "Meta": Meta,
                # Set fields_map as a class attribute
                "fields_map": fields_map
            }
        )
        # Use the custom list serializer so that many=True caches individual instances.
        serializer_class.Meta.list_serializer_class = IndividualCachingListSerializer

        # Iterate over the model's fields.
        model_name = config.orm_provider.get_model_name(model)
        allowed_fields = extract_fields(fields_map, "", model_name)

        # Iterate over the model's fields.
        if allowed_fields:
            for field in model._meta.get_fields():
                # Skip fields that won't be presented
                if field.name not in allowed_fields:
                    continue
                if getattr(field, "auto_created", False) and not field.concrete:
                    continue
                if field.is_relation:
                    # Determine if this is a many-to-many or one-to-many field
                    # ManyToManyField, ManyToManyRel, ManyToOneRel
                    is_many = field.many_to_many or field.one_to_many
                    serializer_class._declared_fields[field.name] = RelatedFieldWithRepr(
                        queryset=field.related_model.objects.all(),
                        required=not (field.null or field.blank),
                        depth=depth,
                        allow_null=field.null,
                        many=is_many,
                        fields_map=fields_map
                    )
                else:
                    custom_field_serializer = get_custom_serializer(field.__class__)
                    if custom_field_serializer:
                        serializer_class.serializer_field_mapping[field.__class__] = (
                            custom_field_serializer
                        )

        # Inject additional computed fields from the registry, if any.
        try:
            model_config = registry.get_config(model)
        except ValueError:
            model_config = None

        mapping = serializers.ModelSerializer.serializer_field_mapping
        for additional_field in model_config.additional_fields:
            drf_field_class = mapping.get(type(additional_field.field))
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
            # Set the source attribute so that the serializer looks for this computed field.
            serializer_field.source = additional_field.name
            serializer_class._declared_fields[additional_field.name] = serializer_field
        return serializer_class

    def cached_data(self) -> Any:
        """
        Return the serialized data.
        If a cache backend is configured, first try to retrieve a cached result
        using a key computed from the model, instance, depth, and fields_map.
        If not found, compute the serialization, cache it (registering all dependencies
        that were logged during this serialization pass), and return the result.
        
        Respects model-specific cache TTL settings from the registry.
        """
        model = self.Meta.model
        model_config = registry.get_config(model)

        # If cache_ttl is 0, caching is disabled for this model
        if model_config.cache_ttl == 0:
            return self.data
        
        if self.cache_backend is not None:
            get_model_name = config.orm_provider.get_model_name
            cache_key = self.generate_cache_key(
                model, self.instance, self.depth, self.fields_map, get_model_name
            )
            print(f"returning cache key {cache_key}")
            cached = self.get_cached_result(cache_key)
            print(f"cache result is {json.dumps(cached)}")
            if cached is not None:
                return cached
            
            # Get model name and allowed fields
            model_name = config.orm_provider.get_model_name(model)
            allowed_fields = extract_fields(self.fields_map, "", model_name)

            # Register the instance itself as a dependency BEFORE serializing
            self.log_dependency(self.instance, get_model_name)

            # For ForeignKey fields, register those as dependencies too
            for field in model._meta.get_fields():
                # Skip fields that won't be presented
                if field.name not in allowed_fields:
                    continue

                if (
                    field.is_relation
                    and field.concrete
                    and not getattr(field, "auto_created", False)
                ):
                    related_instance = getattr(self.instance, field.name, None)
                    if (
                        related_instance
                        and hasattr(related_instance, "pk")
                        and related_instance.pk
                    ):
                        self.log_dependency(related_instance, get_model_name)

            result = self.data  # Trigger full serialization.
                
            # Cache the result with the model-specific TTL
            self.cache_result(cache_key, result, model_config.cache_ttl)
            return result
        else:
            return self.data


class DRFDynamicSerializer(AbstractDataSerializer):
    """
    The abstract base class for DRF serialization.

    In this design, the private `_serialize` method instantiates a DynamicModelSerializer
    with a fields_map set at the class level. This ensures all dependencies are properly
    collected throughout the serialization chain.
    """

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
        
        # Create the serializer class with fields_map as a class attribute
        serializer_class = DynamicModelSerializer.for_model(
            model=model, 
            depth=depth, 
            fields_map=fields_map
        )
        
        # Pass explicit parameters without fields_map
        serializer = serializer_class(
            data,
            many=many,
            depth=depth,
            cache_backend=config.cache_backend,
            dependency_store=config.dependency_store,
            request=request,
            current_path=""
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
        
        serializer = self._serialize(
            data=data, 
            model=model,
            depth=depth,
            fields_map=fields_map, 
            many=many, 
            request=request
        )
        return serializer.cached_data()

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

        # Create serializer class with fields_map as a class attribute
        serializer_class = DynamicModelSerializer.for_model(
            model=model, 
            depth=0, 
            fields_map=fields_map
        )

        model_config = registry.get_config(model)

        if model_config.pre_hooks:
            for hook in model_config.pre_hooks:
                data = hook(data, request=request)

        # Create serializer without passing fields_map
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
        
        # Create serializer class with fields_map as a class attribute
        serializer_class = DynamicModelSerializer.for_model(
            model=model, 
            depth=0,  # No need for depth during save
            fields_map=unrestricted_fields_map  # Use all fields
        )
        
        # Create serializer without passing fields_map
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