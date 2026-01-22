"""
Public utility functions for generating schemas and serializers for arbitrary models.

These functions bypass the StateZero registry and accept an explicit ModelConfig,
while still respecting the custom serializers and schema overrides from the global config.
"""
from typing import Type, Set, Optional, Any, Dict

from django.db import models
from django.db.models.fields.related import ForeignObjectRel, OneToOneRel
from rest_framework import serializers

from statezero.adaptors.django.config import config
from statezero.adaptors.django.serializers import (
    DynamicModelSerializer,
    FlexiblePrimaryKeyRelatedField,
    FExpressionMixin,
    get_custom_serializer,
)
from statezero.adaptors.django.schemas import DjangoSchemaGenerator
from statezero.core.config import ModelConfig
from statezero.core.classes import (
    FieldFormat,
    FieldType,
    ModelSchemaMetadata,
    SchemaFieldMetadata,
)


def generate_schema(
    model: Type[models.Model],
    model_config: ModelConfig,
    allowed_fields: Optional[Set[str]] = None,
) -> ModelSchemaMetadata:
    """
    Generate a schema for a Django model using an explicit ModelConfig.

    This bypasses the StateZero registry but respects config.schema_overrides.

    Args:
        model: The Django model class
        model_config: The ModelConfig to use (not looked up from registry)
        allowed_fields: Optional set of field names to include

    Returns:
        ModelSchemaMetadata

    Example:
        from statezero.adaptors.django.utils import generate_schema
        from statezero.core.config import ModelConfig

        my_config = ModelConfig(
            model=SomeModel,
            fields="__all__",
            filterable_fields="__all__",
        )
        schema = generate_schema(SomeModel, my_config)
    """
    generator = _StandaloneSchemaGenerator()
    return generator.generate_schema(
        model=model,
        model_config=model_config,
        global_schema_overrides=config.schema_overrides,
        allowed_fields=allowed_fields,
    )


def generate_serializer_class(
    model: Type[models.Model],
    model_config: ModelConfig,
    fields: Optional[Set[str]] = None,
) -> Type[serializers.ModelSerializer]:
    """
    Create a serializer class for a Django model using an explicit ModelConfig.

    This bypasses the StateZero registry but respects config.custom_serializers.

    Args:
        model: The Django model class
        model_config: The ModelConfig to use (not looked up from registry)
        fields: Optional set of field names to include. If None, includes all fields.

    Returns:
        A DynamicModelSerializer subclass

    Example:
        from statezero.adaptors.django.utils import generate_serializer_class
        from statezero.core.config import ModelConfig

        my_config = ModelConfig(
            model=SomeModel,
            fields="__all__",
        )
        SerializerClass = generate_serializer_class(SomeModel, my_config)
        data = SerializerClass(instance).data
    """
    return _create_serializer_class(model, model_config, fields)


class _StandaloneSchemaGenerator(DjangoSchemaGenerator):
    """Schema generator that accepts ModelConfig directly instead of registry lookup."""

    def generate_schema(
        self,
        model: Type,
        model_config: ModelConfig,
        global_schema_overrides: Dict[Any, Any],
        allowed_fields: Optional[Set[str]] = None,
    ) -> ModelSchemaMetadata:
        """Generate schema using the provided model_config."""
        from django.conf import settings

        properties: Dict[str, SchemaFieldMetadata] = {}
        relationships: Dict[str, Dict[str, Any]] = {}

        # Process all concrete fields and many-to-many fields
        all_fields = list(model._meta.fields) + list(model._meta.many_to_many)
        all_field_names: Set[str] = set()
        db_field_names: Set[str] = set()

        # Get PK field name to always include it
        pk_field_name = model._meta.pk.name

        if model_config.fields != "__all__":
            # Always include the PK field
            fields_to_include = set(model_config.fields) | {pk_field_name}
            all_fields = [
                field for field in all_fields if field.name in fields_to_include
            ]

        for field in all_fields:
            if getattr(field, "auto_created", False) and not field.concrete:
                continue

            all_field_names.add(field.name)
            db_field_names.add(field.name)

            if (
                allowed_fields is not None
                and allowed_fields != "__all__"
                and field.name not in allowed_fields
            ):
                continue

            if field == model._meta.pk:
                schema_field = self.get_pk_schema(field)
            else:
                schema_field = self.get_field_metadata(field, global_schema_overrides)

            properties[field.name] = schema_field

            if field.is_relation:
                relationships[field.name] = {
                    "type": self.get_relation_type(field),
                    "model": config.orm_provider.get_model_name(field.related_model),
                    "class_name": field.related_model.__name__,
                    "primary_key_field": field.related_model._meta.pk.name,
                }

        # Process reverse relationships if explicitly declared
        if model_config.fields != "__all__":
            for field in model._meta.get_fields():
                if isinstance(field, ForeignObjectRel) and field.name in model_config.fields:
                    if (
                        allowed_fields is not None
                        and allowed_fields != "__all__"
                        and field.name not in allowed_fields
                    ):
                        continue

                    all_field_names.add(field.name)
                    related_model = field.related_model

                    if isinstance(field, OneToOneRel):
                        related_pk_field = related_model._meta.pk
                        schema_field = SchemaFieldMetadata(
                            type=self.get_pk_type(related_pk_field),
                            title=field.name.replace("_", " ").title(),
                            required=False,
                            nullable=True,
                            format=FieldFormat.FOREIGN_KEY,
                            read_only=True,
                        )
                        relation_type = FieldFormat.FOREIGN_KEY
                    else:
                        schema_field = SchemaFieldMetadata(
                            type=FieldType.ARRAY,
                            title=field.name.replace("_", " ").title(),
                            required=False,
                            nullable=False,
                            format=FieldFormat.MANY_TO_MANY,
                            read_only=True,
                        )
                        relation_type = FieldFormat.MANY_TO_MANY

                    properties[field.name] = schema_field
                    relationships[field.name] = {
                        "type": relation_type,
                        "model": config.orm_provider.get_model_name(related_model),
                        "class_name": related_model.__name__,
                        "primary_key_field": related_model._meta.pk.name,
                    }

        # Process additional fields
        for field in model_config.additional_fields or []:
            if (
                allowed_fields is not None
                and allowed_fields != "__all__"
                and field.name not in allowed_fields
            ):
                continue

            field.field.name = field.name
            field.field.title = field.title

            schema_field = self.get_field_metadata(field.field, global_schema_overrides)
            schema_field.title = field.title or schema_field.title
            schema_field.read_only = True
            properties[field.name] = schema_field
            all_field_names.add(field.name)

        # Build field sets
        filterable_fields = (
            db_field_names
            if model_config.filterable_fields == "__all__"
            else model_config.filterable_fields or set()
        )
        searchable_fields = (
            db_field_names
            if model_config.searchable_fields == "__all__"
            else model_config.searchable_fields or set()
        )
        ordering_fields = (
            db_field_names
            if model_config.ordering_fields == "__all__"
            else model_config.ordering_fields or set()
        )

        default_ordering = None
        if hasattr(model._meta, "ordering") and model._meta.ordering:
            default_ordering = list(model._meta.ordering)

        display_data = None
        if model_config.display:
            display_data = self._serialize_display_metadata(model_config.display)

        return ModelSchemaMetadata(
            model_name=config.orm_provider.get_model_name(model),
            title=str(model._meta.verbose_name).title(),
            plural_title=(
                str(model._meta.verbose_name_plural).title()
                if hasattr(model._meta, "verbose_name_plural")
                else model.__name__ + "s"
            ),
            primary_key_field=model._meta.pk.name,
            filterable_fields=filterable_fields,
            searchable_fields=searchable_fields,
            ordering_fields=ordering_fields,
            properties=properties,
            relationships=relationships,
            default_ordering=default_ordering,
            definitions=self.definitions,
            class_name=model.__name__,
            date_format=getattr(settings, "REST_FRAMEWORK", {}).get("DATE_FORMAT", "iso-8601"),
            datetime_format=getattr(settings, "REST_FRAMEWORK", {}).get("DATETIME_FORMAT", "iso-8601"),
            time_format=getattr(settings, "REST_FRAMEWORK", {}).get("TIME_FORMAT", "iso-8601"),
            display=display_data,
        )


class _StandaloneModelSerializer(FExpressionMixin, serializers.ModelSerializer):
    """
    A standalone serializer that doesn't use fields_map_context filtering.
    This is used by generate_serializer_class to avoid the DynamicModelSerializer
    __init__ filtering behavior.
    """
    repr = serializers.SerializerMethodField()

    def get_repr(self, obj):
        img_repr = obj.__img__() if hasattr(obj, "__img__") else None
        str_repr = str(obj)
        return {"str": str_repr, "img": img_repr}


def _create_serializer_class(
    model: Type[models.Model],
    model_config: ModelConfig,
    fields: Optional[Set[str]] = None,
) -> Type[serializers.ModelSerializer]:
    """Create a serializer class using explicit ModelConfig."""
    pk_field = model._meta.pk.name

    # If no fields specified, get all field names
    if fields is None:
        fields = set()
        for field in model._meta.get_fields():
            if getattr(field, "auto_created", False) and not field.concrete:
                continue
            fields.add(field.name)
        # Add additional fields from config
        for af in model_config.additional_fields or []:
            fields.add(af.name)

    # Always include pk and repr
    fields = fields | {pk_field, "repr"}

    # Create Meta class with explicit fields list
    Meta = type("Meta", (), {
        "model": model,
        "fields": list(fields),
        "read_only_fields": (pk_field,),
    })

    # Create serializer class (not inheriting DynamicModelSerializer to avoid filtering)
    serializer_class = type(
        f"Standalone{model.__name__}Serializer",
        (_StandaloneModelSerializer,),
        {"Meta": Meta}
    )

    # Setup custom serializers (uses config.custom_serializers)
    for field in model._meta.get_fields():
        if field.name not in fields:
            continue
        if getattr(field, "auto_created", False) and not field.concrete:
            continue
        if not field.is_relation:
            custom_field_serializer = get_custom_serializer(field.__class__)
            if custom_field_serializer:
                serializer_class.serializer_field_mapping[field.__class__] = custom_field_serializer

    # Setup computed fields from model_config
    mapping = serializers.ModelSerializer.serializer_field_mapping
    for additional_field in model_config.additional_fields or []:
        if additional_field.name not in fields:
            continue
        drf_field_class = mapping.get(type(additional_field.field))
        if not drf_field_class:
            continue

        field_kwargs = {"read_only": True}
        if additional_field.title:
            field_kwargs["label"] = additional_field.title

        if isinstance(additional_field.field, models.DecimalField):
            field_kwargs["max_digits"] = additional_field.field.max_digits
            field_kwargs["decimal_places"] = additional_field.field.decimal_places
        elif isinstance(additional_field.field, models.CharField):
            field_kwargs["max_length"] = additional_field.field.max_length

        serializer_field = drf_field_class(**field_kwargs)
        serializer_field.source = additional_field.name
        serializer_class._declared_fields[additional_field.name] = serializer_field

    # Setup relation fields
    configured_fields = model_config.fields
    for field in model._meta.get_fields():
        if field.name not in fields:
            continue

        if isinstance(field, ForeignObjectRel):
            if configured_fields == "__all__" or field.name not in configured_fields:
                continue
            if isinstance(field, OneToOneRel):
                serializer_class._declared_fields[field.name] = serializers.PrimaryKeyRelatedField(
                    read_only=True, many=False
                )
            else:
                serializer_class._declared_fields[field.name] = serializers.PrimaryKeyRelatedField(
                    read_only=True, many=True
                )
            continue

        if getattr(field, "auto_created", False) and not field.concrete:
            continue

        if field.is_relation:
            queryset = field.related_model.objects.all()
            serializer_class._declared_fields[field.name] = FlexiblePrimaryKeyRelatedField(
                queryset=queryset,
                required=not (field.null or field.blank),
                allow_null=field.null,
                many=field.many_to_many or field.one_to_many,
            )

    return serializer_class
