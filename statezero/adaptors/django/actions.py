import os
from django.apps import apps
from rest_framework.response import Response
from rest_framework import fields, serializers
from django.db import models
from statezero.core.actions import action_registry

class DjangoActionSchemaGenerator:
    """Django-specific action schema generator that matches StateZero model schema format"""

    @staticmethod
    def generate_actions_schema():
        """Generate schema for all registered actions matching StateZero model schema format"""
        actions_schema = {}
        all_app_configs = list(apps.get_app_configs())

        # Pre-compute app paths once to avoid O(n*m) repeated os.path.abspath calls
        app_paths = [(app_config, os.path.abspath(app_config.path)) for app_config in all_app_configs]

        for action_name, action_config in action_registry.get_actions().items():
            func = action_config.get("function")
            if not func:
                raise ValueError(
                    f"Action '{action_name}' is missing a function and cannot be processed."
                )

            func_path = os.path.abspath(func.__code__.co_filename)
            found_app = None
            found_app_path_len = 0

            for app_config, app_path in app_paths:
                if func_path.startswith(app_path + os.sep):
                    if not found_app or len(app_path) > found_app_path_len:
                        found_app = app_config
                        found_app_path_len = len(app_path)

            if not found_app:
                raise LookupError(
                    f"Action '{action_name}' from file '{func_path}' does not belong to any "
                    f"installed Django app. Please ensure the parent app is in INSTALLED_APPS."
                )

            app_name = found_app.label
            docstring = action_config.get("docstring")

            input_properties, input_relationships = DjangoActionSchemaGenerator._get_serializer_schema(
                action_config["serializer"]
            )
            response_properties, response_relationships = DjangoActionSchemaGenerator._get_serializer_schema(
                action_config["response_serializer"]
            )

            # Serialize display metadata if present
            display_data = None
            if action_config.get("display"):
                display_data = DjangoActionSchemaGenerator._serialize_display_metadata(
                    action_config["display"]
                )

            schema_info = {
                "action_name": action_name,
                "app": app_name,
                "title": action_name.replace("_", " ").title(),
                "docstring": docstring,
                "class_name": "".join(
                    word.capitalize() for word in action_name.split("_")
                ),
                "input_properties": input_properties,
                "response_properties": response_properties,
                "relationships": {**input_relationships, **response_relationships},
                "permissions": [
                    perm.__name__ for perm in action_config.get("permissions", [])
                ],
                "display": display_data,
            }
            actions_schema[action_name] = schema_info

        return Response({"actions": actions_schema, "count": len(actions_schema)})

    @staticmethod
    def _get_serializer_schema(serializer_class):
        if not serializer_class:
            return {}, {}
        try:
            serializer_instance = serializer_class()
            properties = {}
            relationships = {}
            for field_name, field in serializer_instance.fields.items():
                relation_info = DjangoActionSchemaGenerator._get_relation_info(field)
                if relation_info:
                    relationships[field_name] = relation_info
                
                field_info = {
                    "type": DjangoActionSchemaGenerator._get_field_type(field),
                    "title": getattr(field, "label")
                    or field_name.replace("_", " ").title(),
                    "required": field.required,
                    "description": getattr(field, "help_text", None),
                    "nullable": getattr(field, "allow_null", False),
                    "format": DjangoActionSchemaGenerator._get_field_format(field),
                    "max_length": getattr(field, "max_length", None),
                    "choices": DjangoActionSchemaGenerator._get_field_choices(field),
                    "default": DjangoActionSchemaGenerator._get_field_default(field),
                    "validators": [],
                    "max_digits": getattr(field, "max_digits", None),
                    "decimal_places": getattr(field, "decimal_places", None),
                    "read_only": field.read_only,
                    "ref": None,
                }
                if hasattr(field, "max_value") and field.max_value is not None:
                    field_info["max_value"] = field.max_value
                if hasattr(field, "min_value") and field.min_value is not None:
                    field_info["min_value"] = field.min_value
                if hasattr(field, "min_length") and field.min_length is not None:
                    field_info["min_length"] = field.min_length
                properties[field_name] = field_info
            return properties, relationships
        except Exception as e:
            print(f"Could not inspect serializer: {str(e)}")
            raise e

    @staticmethod
    def _get_field_type(field):
        if isinstance(field, serializers.PrimaryKeyRelatedField):
            pk_field = field.queryset.model._meta.pk
            if isinstance(pk_field, (models.UUIDField, models.CharField)):
                return "string"
            return "integer"

        # Handle nested serializers (many=True creates a ListSerializer)
        if isinstance(field, serializers.ListSerializer):
            return "array"

        # Handle nested serializers (single nested serializer)
        if isinstance(field, serializers.Serializer):
            return "object"

        type_mapping = {
            fields.BooleanField: "boolean",
            fields.CharField: "string",
            fields.EmailField: "string",
            fields.URLField: "string",
            fields.UUIDField: "string",
            fields.IntegerField: "integer",
            fields.FloatField: "number",
            fields.DecimalField: "string",
            fields.DateField: "string",
            fields.DateTimeField: "string",
            fields.TimeField: "string",
            fields.JSONField: "object",
            fields.DictField: "object",
            fields.ListField: "array",
            serializers.ManyRelatedField: "array",
        }
        return type_mapping.get(type(field), "string")

    @staticmethod
    def _get_field_format(field):
        format_mapping = {
            fields.EmailField: "email",
            fields.URLField: "uri",
            fields.UUIDField: "uuid",
            fields.DateField: "date",
            fields.DateTimeField: "date-time",
            fields.TimeField: "time",
            serializers.ManyRelatedField: "many-to-many",
            serializers.PrimaryKeyRelatedField: "foreign-key",
        }
        return format_mapping.get(type(field))

    @staticmethod
    def _get_field_choices(field):
        # Skip relational fields - they expose queryset as "choices" but that's not
        # the same as actual choice fields. We don't want to enumerate all related
        # model instances as enum values.
        if isinstance(field, (serializers.PrimaryKeyRelatedField, serializers.ManyRelatedField)):
            return None

        if hasattr(field, "choices") and field.choices:
            choices = field.choices
            
            # Handle dict format: {'low': 'Low', 'high': 'High'}
            if isinstance(choices, dict):
                return choices
            
            # Handle list/tuple format: [('low', 'Low'), ('high', 'High')]
            elif isinstance(choices, (list, tuple)):
                try:
                    # Return dict with value->label mapping (same as model)
                    return {str(choice[0]): choice[1] for choice in choices}
                except (IndexError, TypeError) as e:
                    raise ValueError(
                        f"Invalid choice format for field '{field}'. Expected list of tuples "
                        f"like [('value', 'display')], but got: {choices}. Error: {e}"
                    )
            
            # Handle unexpected format
            else:
                raise ValueError(
                    f"Unsupported choice format for field '{field}'. Expected dict or list of tuples, "
                    f"but got {type(choices)}: {choices}"
                )
        
        return None

    @staticmethod
    def _get_field_default(field):
        if hasattr(field, "default"):
            default = field.default
            if default is fields.empty:
                return None
            if callable(default):
                return None
            return default
        return None
    
    @staticmethod
    def _get_relation_info(field):
        relation_type = DjangoActionSchemaGenerator._get_field_format(field)
        if not relation_type in ["foreign-key", "one-to-one", "many-to-many"]:
            return None

        if isinstance(field, serializers.PrimaryKeyRelatedField):
            model = field.queryset.model
            return {
                "type": relation_type,
                "model": f"{model._meta.app_label}.{model._meta.model_name}",
                "class_name": model.__name__,
                "primary_key_field": model._meta.pk.name,
            }
        if isinstance(field, serializers.ManyRelatedField):
            model = field.child_relation.queryset.model
            return {
                "type": relation_type,
                "model": f"{model._meta.app_label}.{model._meta.model_name}",
                "class_name": model.__name__,
                "primary_key_field": model._meta.pk.name,
            }
        return None

    @staticmethod
    def _serialize_display_metadata(display):
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