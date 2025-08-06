import os
from django.apps import apps
from rest_framework.response import Response
from rest_framework import fields
from statezero.core.actions import action_registry


class DjangoActionSchemaGenerator:
    """Django-specific action schema generator that matches StateZero model schema format"""

    @staticmethod
    def generate_actions_schema():
        """Generate schema for all registered actions matching StateZero model schema format"""
        actions_schema = {}
        all_app_configs = list(apps.get_app_configs())

        for action_name, action_config in action_registry.get_actions().items():
            func = action_config.get("function")
            if not func:
                raise ValueError(
                    f"Action '{action_name}' is missing a function and cannot be processed."
                )

            # --- START: New file-path based app discovery ---
            func_path = os.path.abspath(func.__code__.co_filename)
            found_app = None

            # Find the app that contains this function's file.
            # We look for the most specific app by finding the longest matching path.
            for app_config in all_app_configs:
                app_path = os.path.abspath(app_config.path)
                if func_path.startswith(app_path + os.sep):
                    if not found_app or len(app_path) > len(
                        os.path.abspath(found_app.path)
                    ):
                        found_app = app_config

            if not found_app:
                raise LookupError(
                    f"Action '{action_name}' from file '{func_path}' does not belong to any "
                    f"installed Django app. Please ensure the parent app is in INSTALLED_APPS."
                )

            app_name = found_app.label
            # --- END: New discovery logic ---

            schema_info = {
                "action_name": action_name,
                "app": app_name,
                "title": action_name.replace("_", " ").title(),
                "class_name": "".join(
                    word.capitalize() for word in action_name.split("_")
                ),
                "input_properties": DjangoActionSchemaGenerator._get_serializer_schema(
                    action_config["serializer"]
                ),
                "response_properties": DjangoActionSchemaGenerator._get_serializer_schema(
                    action_config["response_serializer"]
                ),
                "permissions": [
                    perm.__name__ for perm in action_config.get("permissions", [])
                ],
            }
            actions_schema[action_name] = schema_info

        return Response({"actions": actions_schema, "count": len(actions_schema)})

    # ... The rest of the helper methods are unchanged ...
    @staticmethod
    def _get_serializer_schema(serializer_class):
        if not serializer_class:
            return {}
        try:
            serializer_instance = serializer_class()
            properties = {}
            for field_name, field in serializer_instance.fields.items():
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
            return properties
        except Exception as e:
            return {"error": f"Could not inspect serializer: {str(e)}"}

    @staticmethod
    def _get_field_type(field):
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
        }
        return format_mapping.get(type(field))

    @staticmethod
    def _get_field_choices(field):
        if hasattr(field, "choices") and field.choices:
            return [choice[0] for choice in field.choices]
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