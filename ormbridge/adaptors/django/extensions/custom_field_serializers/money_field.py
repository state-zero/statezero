import json
from decimal import Decimal, InvalidOperation
from typing import Dict, Tuple

from djmoney.contrib.django_rest_framework.fields import MoneyField
from djmoney.money import Money
from rest_framework import serializers

from ormbridge.core.classes import FieldFormat, FieldType, SchemaFieldMetadata
from ormbridge.core.interfaces import AbstractSchemaOverride


class MoneyFieldSerializer(serializers.Field):

    def __init__(self, **kwargs):
        # Define max_digits and decimal_places based on your requirements
        self.max_digits = kwargs.pop("max_digits", 14)
        self.decimal_places = kwargs.pop("decimal_places", 2)
        super().__init__(**kwargs)

    def to_representation(self, value):
        # Use djmoney's representation for the amount
        print("money field to representation called")
        djmoney_field = MoneyField(
            max_digits=self.max_digits, decimal_places=self.decimal_places
        )
        amount_representation = djmoney_field.to_representation(value)
        return {"amount": amount_representation, "currency": value.currency.code}

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                "Input value for moneyfield must be an object with amount and currency keys"
            )
        try:
            amount = data["amount"]
            currency = data["currency"]

            # Ensure the amount is converted to a Decimal, whether it's a string or a number
            if isinstance(amount, (str, float, int)):
                amount = Decimal(amount)

            return Money(amount, currency)
        except KeyError:
            raise serializers.ValidationError(
                "Invalid input for MoneyField. Expecting 'amount' and 'currency'."
            )
        except InvalidOperation:
            raise serializers.ValidationError(
                "Invalid amount format. Must be a valid decimal number."
            )


# Custom serializer for MoneyField.
class MoneyFieldSerializer(serializers.Field):
    def __init__(self, **kwargs):
        self.max_digits = kwargs.pop("max_digits", 14)
        self.decimal_places = kwargs.pop("decimal_places", 2)
        super().__init__(**kwargs)

    def to_representation(self, value):
        djmoney_field = MoneyField(
            max_digits=self.max_digits, decimal_places=self.decimal_places
        )
        amount_representation = djmoney_field.to_representation(value)
        return {"amount": amount_representation, "currency": value.currency.code}

    def to_internal_value(self, data) -> Money:
        if isinstance(data, Money):
            return data
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                f"Input must be an object with 'amount' and 'currency' keys but we got {data} of type {type(data)}"
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
        # Return a schema metadata object that references this definition.
        schema = SchemaFieldMetadata(
            type=FieldType.OBJECT,
            title="Money",
            required=True,
            nullable=field.null,
            format=FieldFormat.MONEY,
            description=field.help_text or "Money field",
            ref=f"#/components/schemas/{key}",
        )

        return schema, definition, key
