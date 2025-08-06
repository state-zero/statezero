from rest_framework.response import Response
from rest_framework import fields
from statezero.core.actions import action_registry


class DjangoActionSchemaGenerator:
    """Django-specific action schema generator that matches StateZero model schema format"""

    @staticmethod
    def generate_actions_schema():
        """Generate schema for all registered actions matching StateZero model schema format"""
        actions_schema = {}

        for action_name, action_config in action_registry.get_actions().items():
            schema_info = {
                "action_name": action_name,
                "title": action_name.replace("_", " ").title(),
                "class_name": "".join(
                    word.capitalize() for word in action_name.split("_")
                ),
                "module": action_config["module"],
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

    @staticmethod
    def _get_serializer_schema(serializer_class):
        """Extract schema information from a DRF serializer matching StateZero field format"""
        if not serializer_class:
            return {}

        try:
            # Create temporary instance to inspect fields
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
                    "validators": [],  # Could be populated with validator info if needed
                    "max_digits": getattr(field, "max_digits", None),
                    "decimal_places": getattr(field, "decimal_places", None),
                    "read_only": field.read_only,
                    "ref": None,  # Actions don't have model references like ForeignKeys
                }

                # Add min/max values for numeric fields
                if hasattr(field, "max_value") and field.max_value is not None:
                    field_info["max_value"] = field.max_value
                if hasattr(field, "min_value") and field.min_value is not None:
                    field_info["min_value"] = field.min_value
                if hasattr(field, "min_length") and field.min_length is not None:
                    field_info["min_length"] = field.min_length

                properties[field_name] = field_info

            return properties
        except Exception as e:
            # Return minimal info if serializer inspection fails
            return {"error": f"Could not inspect serializer: {str(e)}"}

    @staticmethod
    def _get_field_type(field):
        """Get field type matching StateZero schema format"""
        type_mapping = {
            fields.BooleanField: "boolean",
            fields.CharField: "string",
            fields.EmailField: "string",
            fields.URLField: "string",
            fields.UUIDField: "string",
            fields.IntegerField: "integer",
            fields.FloatField: "number",
            fields.DecimalField: "string",  # StateZero uses string for decimals
            fields.DateField: "string",
            fields.DateTimeField: "string",
            fields.TimeField: "string",
            fields.JSONField: "object",
            fields.DictField: "object",
            fields.ListField: "array",
        }

        field_type = type(field)
        return type_mapping.get(
            field_type, "string"
        )  # Default to string like StateZero

    @staticmethod
    def _get_field_format(field):
        """Get field format matching StateZero schema format"""
        format_mapping = {
            fields.EmailField: "email",
            fields.URLField: "uri",
            fields.UUIDField: "uuid",
            fields.DateField: "date",
            fields.DateTimeField: "date-time",
            fields.TimeField: "time",
            fields.IntegerField: None,  # No format for basic integer
            fields.CharField: None,  # No format for basic string
        }

        field_type = type(field)
        return format_mapping.get(field_type, None)

    @staticmethod
    def _get_field_choices(field):
        """Get field choices in the format StateZero expects"""
        if hasattr(field, "choices") and field.choices:
            # Return list of choice values (not tuples)
            return [choice[0] for choice in field.choices]
        return None

    @staticmethod
    def _get_field_default(field):
        """Get field default value, handling DRF's special cases"""
        if hasattr(field, "default"):
            default = field.default
            # Handle DRF's special empty/missing values
            if default is fields.empty:
                return None
            # For callable defaults, we can't evaluate them safely
            if callable(default):
                return None
            return default
        return None
