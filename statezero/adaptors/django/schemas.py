from typing import Any, Dict, List, Literal, Optional, Set, Type, Union

from django.apps import apps
from django.db import models
from django.db.models.fields.related import ForeignObjectRel, ManyToOneRel, ManyToManyRel, OneToOneRel
from djmoney.models.fields import MoneyField
from django.conf import settings

from statezero.adaptors.django.config import config, registry
from statezero.core.classes import (
    FieldFormat,
    FieldType,
    ModelSchemaMetadata,
    SchemaFieldMetadata,
)

from statezero.core.interfaces import AbstractSchemaGenerator, AbstractSchemaOverride
from statezero.core.types import ORMField


class DjangoSchemaGenerator(AbstractSchemaGenerator):
    def __init__(self):
        # Initialize definitions as an empty dictionary.
        self.definitions: Dict[str, Dict[str, Any]] = {}

    def generate_schema(
        self,
        model: Type,
        global_schema_overrides: Dict[ORMField, dict],  # type:ignore
        additional_fields: List[Any],
        definitions: Dict[str, Dict[str, Any]] = {},
        allowed_fields: Optional[Set[str]] = None,  # Pre-computed allowed fields.
    ) -> ModelSchemaMetadata:
        properties: Dict[str, SchemaFieldMetadata] = {}
        relationships: Dict[str, Dict[str, Any]] = {}

        # Get model config from registry
        model_config = registry.get_config(model)

        # Process all concrete fields and many-to-many fields
        all_fields = list(model._meta.fields) + list(model._meta.many_to_many)
        all_field_names: Set[str] = set()
        db_field_names: Set[str] = set()

        if model_config.fields != "__all__":
            all_fields = [
                field for field in all_fields if field.name in model_config.fields
            ]

        for field in all_fields:
            # Skip auto-created reverse relations.
            if getattr(field, "auto_created", False) and not field.concrete:
                continue

            all_field_names.add(field.name)
            db_field_names.add(field.name)

            # If allowed_fields is provided and is not the magic "__all__", skip fields not in the allowed set.
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

            # If the field represents a relation, record that.
            if field.is_relation:
                relationships[field.name] = {
                    "type": self.get_relation_type(field),
                    "model": config.orm_provider.get_model_name(field.related_model),
                    "class_name": field.related_model.__name__,
                    "primary_key_field": field.related_model._meta.pk.name,
                }

        # Process reverse relationships (ForeignObjectRel) that are explicitly declared in fields
        if model_config.fields != "__all__":
            for field in model._meta.get_fields():
                # Only process reverse relations that are explicitly in the fields config
                if isinstance(field, ForeignObjectRel) and field.name in model_config.fields:
                    # Skip if not in allowed_fields
                    if (
                        allowed_fields is not None
                        and allowed_fields != "__all__"
                        and field.name not in allowed_fields
                    ):
                        continue

                    all_field_names.add(field.name)
                    # Note: reverse relations are NOT added to db_field_names since they're not writable

                    related_model = field.related_model

                    # OneToOneRel (reverse of O2O) → like FK (single object)
                    # ManyToOneRel (reverse of FK) → like M2M (array)
                    # ManyToManyRel (reverse of M2M) → like M2M (array)
                    if isinstance(field, OneToOneRel):
                        # Identical to FK schema, but read-only
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
                        # ManyToOneRel or ManyToManyRel - identical to M2M schema, but read-only
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

                    # Record the relationship
                    relationships[field.name] = {
                        "type": relation_type,
                        "model": config.orm_provider.get_model_name(related_model),
                        "class_name": related_model.__name__,
                        "primary_key_field": related_model._meta.pk.name,
                    }

        # Process any additional fields from the registry
        add_fields = model_config.additional_fields or []
        for field in add_fields:
            # If allowed_fields is provided and is not "__all__", skip additional fields not allowed.
            if (
                allowed_fields is not None
                and allowed_fields != "__all__"
                and field.name not in allowed_fields
            ):
                continue

            # Ensure the underlying model field has the expected properties.
            field.field.name = field.name
            field.field.title = field.title

            schema_field = self.get_field_metadata(field.field, global_schema_overrides)
            # Override title if provided (in case the model field didn't have one)
            schema_field.title = field.title or schema_field.title
            schema_field.read_only = True  # Always mark additional fields as read-only
            properties[field.name] = schema_field
            all_field_names.add(field.name)

        # Handle "__all__" notation and set up field sets.
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

        # Merge passed definitions with those collected during field processing.
        merged_definitions = {**definitions, **self.definitions}

        # Extract default ordering from model's Meta
        default_ordering = None
        if hasattr(model._meta, "ordering") and model._meta.ordering:
            default_ordering = list(model._meta.ordering)

        # Serialize display metadata if present
        display_data = None
        if model_config.display:
            display_data = self._serialize_display_metadata(model_config.display)

        schema_meta = ModelSchemaMetadata(
            model_name=config.orm_provider.get_model_name(model),
            title=model._meta.verbose_name.title(),
            plural_title=(
                model._meta.verbose_name_plural.title()
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
            definitions=merged_definitions,
            class_name=model.__name__,
            date_format=getattr(settings, "REST_FRAMEWORK", {}).get(
                "DATE_FORMAT", "iso-8601"
            ),
            datetime_format=getattr(settings, "REST_FRAMEWORK", {}).get(
                "DATETIME_FORMAT", "iso-8601"
            ),
            time_format=getattr(settings, "REST_FRAMEWORK", {}).get(
                "TIME_FORMAT", "iso-8601"
            ),
            display=display_data,
        )
        return schema_meta

    def get_pk_schema(self, field: models.Field) -> SchemaFieldMetadata:
        title = self.get_field_title(field)
        description = (
            str(field.help_text)
            if hasattr(field, "help_text") and field.help_text
            else None
        )

        if isinstance(field, models.AutoField):
            return SchemaFieldMetadata(
                type=FieldType.INTEGER,
                title=title,
                required=True,
                nullable=False,
                format=FieldFormat.ID,
                description=description,
                read_only=True,
            )
        elif isinstance(field, models.UUIDField):
            return SchemaFieldMetadata(
                type=FieldType.STRING,
                title=title,
                required=True,
                nullable=False,
                format=FieldFormat.UUID,
                description=description,
                read_only=True,
            )
        elif isinstance(field, models.CharField):
            return SchemaFieldMetadata(
                type=FieldType.STRING,
                title=title,
                required=True,
                nullable=False,
                format=FieldFormat.ID,
                max_length=field.max_length,
                description=description,
                read_only=True,
            )
        else:
            return SchemaFieldMetadata(
                type=FieldType.OBJECT,
                title=title,
                required=True,
                nullable=False,
                format=FieldFormat.ID,
                description=description,
                read_only=True,
            )

    def get_field_metadata(
        self, field: models.Field, global_schema_overrides: Dict[ORMField, dict]
    ) -> SchemaFieldMetadata:  # type:ignore

        # Check for a custom schema override for this field type.
        override: AbstractSchemaOverride = global_schema_overrides.get(field.__class__)
        if override:
            schema, definition, key = override.get_schema(field)
            if definition and key:
                self.definitions[key] = definition
            return schema

        # Process normally
        title = self.get_field_title(field)
        required = self.is_field_required(field)
        nullable = field.null
        choices = (
            {str(choice[0]): choice[1] for choice in field.choices}
            if field.choices
            else None
        )
        max_length = getattr(field, "max_length", None)
        max_digits = getattr(field, "max_digits", None)
        decimal_places = getattr(field, "decimal_places", None)
        description = (
            str(field.help_text)
            if hasattr(field, "help_text") and field.help_text
            else None
        )

        if isinstance(field, models.TextField):
            field_type = FieldType.STRING
            field_format = FieldFormat.TEXT
        elif isinstance(field, models.CharField):
            field_type = FieldType.STRING
            field_format = None
        elif isinstance(field, models.IntegerField):
            field_type = FieldType.INTEGER
            field_format = None
        elif isinstance(field, models.BooleanField):
            field_type = FieldType.BOOLEAN
            field_format = None
        elif isinstance(field, models.DateTimeField):
            field_type = FieldType.STRING
            field_format = FieldFormat.DATETIME
        elif isinstance(field, models.DateField):
            field_type = FieldType.STRING
            field_format = FieldFormat.DATE
        elif isinstance(field, models.TimeField):
            field_type = FieldType.STRING
            field_format = FieldFormat.TIME
        elif isinstance(field, (models.ForeignKey, models.OneToOneField)):
            field_type = self.get_pk_type(field)
            field_format = self.get_relation_type(field)
        elif isinstance(field, models.ManyToManyField):
            field_type = FieldType.ARRAY
            field_format = FieldFormat.MANY_TO_MANY
        elif isinstance(field, models.DecimalField):
            field_type = FieldType.NUMBER
            field_format = FieldFormat.DECIMAL
        elif isinstance(field, models.FileField):
            field_type = FieldType.STRING
            field_format = FieldFormat.FILE_PATH
        elif isinstance(field, models.ImageField):
            field_type = FieldType.STRING
            field_format = FieldFormat.IMAGE_PATH
        elif isinstance(field, models.JSONField):
            field_type = FieldType.OBJECT
            field_format = FieldFormat.JSON
        else:
            field_type = FieldType.OBJECT
            field_format = None

        # Handle callable defaults: ignore if callable or NOT_PROVIDED.
        default = field.default

        if default == models.fields.NOT_PROVIDED:
            default = None
        elif callable(default):
            default = default()

        # Check if field should be read-only (auto_now or auto_now_add)
        read_only = False
        if isinstance(field, (models.DateTimeField, models.DateField, models.TimeField)):
            if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
                read_only = True

        return SchemaFieldMetadata(
            type=field_type,
            title=title,
            required=required,
            nullable=nullable,
            format=field_format,
            max_length=max_length,
            choices=choices,
            default=default,
            validators=[],
            max_digits=max_digits,
            decimal_places=decimal_places,
            description=description,
            read_only=read_only,
        )

    def get_field_title(self, field: models.Field) -> str:
        if field.verbose_name and not hasattr(field, "title"):
            return field.verbose_name.capitalize()
        return field.title or field.name.replace("_", " ").title()

    @staticmethod
    def is_field_required(field: models.Field) -> bool:
        return (
            not field.null
            and field.default == models.fields.NOT_PROVIDED
        )

    def get_relation_type(self, field: models.Field) -> Optional[FieldFormat]:
        if isinstance(field, models.ForeignKey):
            return FieldFormat.FOREIGN_KEY
        elif isinstance(field, models.OneToOneField):
            return FieldFormat.ONE_TO_ONE
        elif isinstance(field, models.ManyToManyField):
            return FieldFormat.MANY_TO_MANY
        return None

    def get_pk_type(self, field: models.Field) -> FieldType:
        target_field = field.target_field if hasattr(field, "target_field") else field
        if isinstance(target_field, (models.UUIDField, models.CharField)):
            return FieldType.STRING
        return FieldType.INTEGER

    @staticmethod
    def _serialize_display_metadata(display) -> Dict[str, Any]:
        """Convert DisplayMetadata dataclass to dict for JSON serialization"""
        from dataclasses import asdict, is_dataclass

        if display is None:
            return None

        if is_dataclass(display):
            return asdict(display)

        # If it's already a dict, return as-is
        if isinstance(display, dict):
            return display

        return None
