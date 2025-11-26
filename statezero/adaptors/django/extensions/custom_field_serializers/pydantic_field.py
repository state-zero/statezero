"""
Custom serializer for django-pydantic-field's SchemaField.

This ensures Pydantic models are serialized as proper dicts using model_dump(mode='json')
instead of being iterated over (which yields key-value pairs like dict.items()).
"""
from rest_framework import serializers


class PydanticSchemaFieldSerializer(serializers.Field):
    """
    Serializer for django-pydantic-field's SchemaField.

    Handles both single Pydantic models and lists of Pydantic models,
    converting them to JSON-serializable dicts using model_dump().
    """

    def __init__(self, **kwargs):
        # Remove JSONField-specific kwargs that DRF may pass
        kwargs.pop('encoder', None)
        kwargs.pop('decoder', None)
        super().__init__(**kwargs)

    def to_representation(self, value):
        if value is None:
            return None

        # Handle list of Pydantic models
        if isinstance(value, list):
            return [self._dump_model(item) for item in value]

        # Handle single Pydantic model
        return self._dump_model(value)

    def _dump_model(self, model):
        """Convert a Pydantic model to a dict using model_dump."""
        if model is None:
            return None

        # If it's already a dict or primitive, return as-is
        if not hasattr(model, 'model_dump'):
            if hasattr(model, 'dict'):
                raise TypeError(
                    "Pydantic v1 is not supported. Please upgrade to Pydantic v2."
                )
            return model

        return model.model_dump(mode='json')

    def to_internal_value(self, data):
        # For write operations, return the data as-is
        # The SchemaField's model field will handle validation/conversion
        return data
