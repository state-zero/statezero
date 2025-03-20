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
from ormbridge.core.constants import ALL_FIELDS
from ormbridge.core.interfaces import AbstractDataSerializer


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
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        fields_map: Dict[str, Set[str]] = self.context.get("fields_map", {})
        model_name = config.orm_provider.get_model_name(self.queryset.model)
        allowed = fields_map.get(model_name)
        if self.depth == 0 and not allowed:
            return self._minimal_representation(value)
        else:
            return self._expanded_representation(value)

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

    def _expanded_representation(self, instance):
        # Get the nearest parent serializer that implement
        serializer_parent = self.parent
        if not hasattr(serializer_parent, "log_dependency") and hasattr(serializer_parent, "parent"):
            serializer_parent = serializer_parent.parent
        serializer_parent.log_dependency(instance, config.orm_provider.get_model_name)
        
        fields_map = self.context.get("fields_map", {})
        serializer_class = DynamicModelSerializer.for_model(
            instance.__class__, depth=self.depth - 1
        )
        # Propagate the parent's dependency registry by shallow-copying the context.
        serializer = serializer_class(
            instance,
            depth=self.depth - 1,
            context={**self.context, "fields_map": fields_map},
        )
        # Use the nested serializer's own caching mechanism.
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
            serializer_instance = self.child.__class__(
                instance=item, context=self.context, depth=self.context.get("depth", 0)
            )
            result.append(serializer_instance.cached_data())
        return result

    def cached_data(self) -> Any:
        """
        Return the cached representation for the list by iterating over each instance.
        """
        return self.to_representation(self.instance)


class DynamicModelSerializer(CachingMixin, serializers.ModelSerializer):
    """
    A dynamic serializer that adds two extra read-only fields ('repr' and 'img'),
    replaces relation fields with RelatedFieldWithRepr, and injects additional computed
    fields from the registry.

    The __init__ method filters fields based on a provided fields_map.
    """

    repr = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.depth = kwargs.pop("depth", 0)
        self.cache_backend = kwargs.pop("cache_backend", config.cache_backend)
        self.dependency_store = kwargs.pop("dependency_store", config.dependency_store)
        super().__init__(*args, **kwargs)
        model_name = config.orm_provider.get_model_name(self.Meta.model)
        fields_map: Dict[str, Set[str]] = self.context.get("fields_map", {})
        allowed = fields_map.get(model_name)
        if allowed is not None and allowed != {ALL_FIELDS}:
            self.fields = {
                name: field for name, field in self.fields.items() if name in allowed
            }

    def get_repr(self, obj) -> Dict[str, Optional[str]]:
        str_repr = str(obj)
        img_repr = obj.__img__() if hasattr(obj, "__img__") else None
        return {"str": str_repr, "img": img_repr}

    class Meta:
        model = None  # To be set dynamically.
        fields = ALL_FIELDS

    @classmethod
    def for_model(cls, model: Type[models.Model], depth: int = 0):
        # Dynamically create a Meta inner class.
        Meta = type("Meta", (), {"model": model, "fields": ALL_FIELDS})
        serializer_class = type(
            f"Dynamic{model.__name__}Serializer", (cls,), {"Meta": Meta}
        )
        # Use the custom list serializer so that many=True caches individual instances.
        serializer_class.Meta.list_serializer_class = IndividualCachingListSerializer

        # Iterate over the model's fields.
        for field in model._meta.get_fields():
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
                    many=is_many
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

        if model_config:
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
        
        # Check if caching is enabled for this model
        try:
            model_config = registry.get_config(model)
            # If cache_ttl is 0, caching is disabled for this model
            if model_config.cache_ttl == 0:
                return self.data
        except ValueError:
            # If model isn't registered, use default caching behavior
            model_config = None
        
        if self.cache_backend is not None:
            fields_map = self.context.get("fields_map", {})
            get_model_name = config.orm_provider.get_model_name
            cache_key = self.generate_cache_key(
                model, self.instance, self.depth, fields_map, get_model_name
            )
            cached = self.get_cached_result(cache_key)
            if cached is not None:
                return cached

            # Register the instance itself as a dependency BEFORE serializing
            self.log_dependency(self.instance, get_model_name)

            # For ForeignKey fields, register those as dependencies too
            for field in model._meta.get_fields():
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
            
            # Get model-specific TTL if available
            ttl = None
            if model_config is not None:
                ttl = model_config.cache_ttl
                
            # Cache the result with the model-specific TTL
            self.cache_result(cache_key, result, ttl)
            return result
        else:
            return self.data

class DRFDynamicSerializer(AbstractDataSerializer):
    """
    The abstract base class for DRF serialization.

    In this design, the private `_serialize` method instantiates a DynamicModelSerializer
    with a context that always includes a fresh dependency registry. That way, when used
    at the top level, the serializer will collect *all* dependencies (even those from nested serializers).
    Meanwhile, when a serializer is used on its own (e.g. caching a home independently),
    it will only collect its own dependencies.
    """

    def _serialize(
        self,
        data: Any,
        model: Type[models.Model],
        depth: int,
        fields_map: Optional[Dict[str, Set[str]]],
        many: bool,
    ) -> DynamicModelSerializer:
        serializer_class = DynamicModelSerializer.for_model(model, depth=depth)
        fm = fields_map.copy() if fields_map is not None else {}
        model_name = config.orm_provider.get_model_name(model)
        if model_name not in fm:
            fm[model_name] = {ALL_FIELDS}
        # Build a base context that includes a fresh dependency registry.
        ctx = {"depth": depth, "fields_map": fm, "dependency_registry": {}}
        serializer = serializer_class(
            data,
            many=many,
            context=ctx,
            depth=depth,
            cache_backend=config.cache_backend,
            dependency_store=config.dependency_store,
        )
        return serializer

    def serialize(
        self,
        data: Any,
        model: Type[models.Model],
        depth: int,
        fields_map: Optional[Dict[str, Set[str]]] = None,
        many: bool = False,
    ) -> Any:
        """
        Public serialization method.
        Instantiates the serializer via `_serialize` and then returns its cached data.
        With the shared dependency registry, the top-level cache key will be associated
        with all nested dependencies (e.g. reservation depends on home, address, postcode),
        while a nested serializer (e.g. home) registers only its own nested dependencies.
        """
        serializer = self._serialize(data, model, depth, fields_map, many)
        return serializer.cached_data()

    def deserialize(
        self,
        model: Type[models.Model],
        data: Dict[str, Any],
        fields_map: Optional[Dict[str, Set[str]]] = None,
        partial: bool = False,
        request: Optional[Any] = None,
    ) -> Dict[str, Any]:
        serializer_class = DynamicModelSerializer.for_model(model)
        model_name = config.orm_provider.get_model_name(model)
        fm = fields_map.copy() if fields_map is not None else {}
        if model_name not in fm:
            fm[model_name] = {ALL_FIELDS}

        try:
            model_config = registry.get_config(model)
        except ValueError:
            model_config = None

        if model_config and model_config.pre_hooks:
            for hook in model_config.pre_hooks:
                data = hook(data, request=request)

        serializer = serializer_class(
            data=data, context={"fields_map": fm}, partial=partial
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
        instance: Optional[Any] = None,
        fields_map: Optional[Dict[str, Set[str]]] = None,
        partial: bool = True
    ) -> Any:
        """
        Save data to create a new instance or update an existing one.
        
        Args:
            model: The model class
            data: Data to save
            instance: Optional existing instance to update (if None, creates new instance)
            fields_map: Optional mapping of field restrictions
            partial: Whether this is a partial update (default True, only relevant for updates)
            
        Returns:
            The saved instance (either created or updated)
        """
        # Get the appropriate serializer class for this model
        serializer_class = DynamicModelSerializer.for_model(model)
        
        # Create context with fields_map if provided
        context = {}
        if fields_map is not None:
            context["fields_map"] = fields_map
        
        # Create the serializer - with or without an instance
        serializer = serializer_class(
            instance=instance,  # Will be None for creation
            data=data,
            context=context,
            partial=partial if instance else False  # partial only makes sense for updates
        )
        
        # Validate the data
        serializer.is_valid(raise_exception=True)
        
        # Save and return the instance
        return serializer.save()
