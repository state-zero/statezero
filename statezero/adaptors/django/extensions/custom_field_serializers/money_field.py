import json
from decimal import Decimal, InvalidOperation
from typing import Dict, Tuple

from djmoney.contrib.django_rest_framework.fields import MoneyField
from djmoney.money import Money
from rest_framework import serializers

from statezero.core.classes import FieldFormat, FieldType, SchemaFieldMetadata
from statezero.core.interfaces import AbstractSchemaOverride

class MoneyFieldSerializer(serializers.Field):
    def __init__(self, **kwargs):
        self.max_digits = kwargs.pop("max_digits", 14)
        self.decimal_places = kwargs.pop("decimal_places", 2)
        super().__init__(**kwargs)

    @classmethod
    def get_prefetch_db_fields(cls, field_name: str):
        """
        Return all database fields required for this field to serialize.
        MoneyField creates two database columns: field_name and field_name_currency.
        """
        return [field_name, f"{field_name}_currency"]

    def to_representation(self, value):
        if value is None:
            return None
        djmoney_field = MoneyField(
            max_digits=self.max_digits, decimal_places=self.decimal_places
        )
        amount_representation = djmoney_field.to_representation(value)
        return {"amount": amount_representation, "currency": value.currency.code}

    def to_internal_value(self, data):
        if data is None:
            return None
        if isinstance(data, Money):
            return data
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                "Input must be an object with 'amount' and 'currency' keys"
            )
        try:
            amount = data["amount"]
            currency = data["currency"]
            if isinstance(amount, (str, float, int)):
                amount = Decimal(amount)
            return Money(amount, currency)
        except KeyError:
            raise serializers.ValidationError("Missing 'amount' or 'currency'")
        except InvalidOperation:
            raise serializers.ValidationError("Invalid decimal format")


class MoneyFieldSchema(AbstractSchemaOverride):
    def __init__(self, *args, **kwargs):
        pass

    def get_schema(
        field: MoneyField,
    ) -> Tuple[SchemaFieldMetadata, Dict[str, str], str]:
        """
        Generate a schema for MoneyField.
        This registers a reusable definition and returns a schema metadata object with a $ref.
        """
        key = field.__class__.__name__  # i.e. "MoneyField"

        definition = {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "currency": {"type": "string"},
            },
        }
        # Get title from verbose_name or field name
        if field.verbose_name:
            title = field.verbose_name.capitalize()
        else:
            title = field.name.replace("_", " ").title()

        # Return a schema metadata object that references this definition.
        schema = SchemaFieldMetadata(
            type=FieldType.OBJECT,
            title=title,
            required=not (field.null or field.blank),
            nullable=field.null,
            format=FieldFormat.MONEY,
            description=str(field.help_text) if field.help_text else None,
            ref=f"#/components/schemas/{key}",
        )

        return schema, definition, key
