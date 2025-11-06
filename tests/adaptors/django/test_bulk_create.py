from django.test import TestCase
from unittest.mock import Mock

from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.serializers import DRFDynamicSerializer
from statezero.core.ast_parser import ASTParser
from tests.django_app.models import DummyModel, DummyRelatedModel


class BulkCreateSerializerTests(TestCase):
    """Test serializer support for many=True in deserialization"""

    def setUp(self):
        self.related = DummyRelatedModel.objects.create(name="Related")
        self.dummy_model_name = config.orm_provider.get_model_name(DummyModel)

    def test_deserialize_with_many_true(self):
        """Test that deserialize with many=True validates multiple items"""
        serializer_wrapper = DRFDynamicSerializer()
        fields_map = {
            self.dummy_model_name: {"name", "value", "related"}
        }

        input_data = [
            {"name": "Item1", "value": 10},
            {"name": "Item2", "value": 20},
            {"name": "Item3", "value": 30}
        ]

        validated_data = serializer_wrapper.deserialize(
            DummyModel,
            input_data,
            fields_map=fields_map,
            many=True
        )

        # Should return a list of validated dicts
        self.assertIsInstance(validated_data, list)
        self.assertEqual(len(validated_data), 3)

        # Check each item
        self.assertEqual(validated_data[0]["name"], "Item1")
        self.assertEqual(validated_data[0]["value"], 10)

        self.assertEqual(validated_data[1]["name"], "Item2")
        self.assertEqual(validated_data[1]["value"], 20)

        self.assertEqual(validated_data[2]["name"], "Item3")
        self.assertEqual(validated_data[2]["value"], 30)

    def test_deserialize_with_many_false(self):
        """Test that deserialize with many=False still works (single item)"""
        serializer_wrapper = DRFDynamicSerializer()
        fields_map = {
            self.dummy_model_name: {"name", "value"}
        }

        input_data = {"name": "SingleItem", "value": 100}

        validated_data = serializer_wrapper.deserialize(
            DummyModel,
            input_data,
            fields_map=fields_map,
            many=False
        )

        # Should return a single dict
        self.assertIsInstance(validated_data, dict)
        self.assertEqual(validated_data["name"], "SingleItem")
        self.assertEqual(validated_data["value"], 100)

    def test_deserialize_many_with_validation_error(self):
        """Test that validation errors are caught for bulk operations"""
        serializer_wrapper = DRFDynamicSerializer()
        fields_map = {
            self.dummy_model_name: {"name", "value"}
        }

        # Include invalid data (value should be int, not string)
        input_data = [
            {"name": "Item1", "value": 10},
            {"name": "Item2", "value": "not_a_number"},  # Invalid
            {"name": "Item3", "value": 30}
        ]

        # Should raise validation error
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            serializer_wrapper.deserialize(
                DummyModel,
                input_data,
                fields_map=fields_map,
                many=True
            )

    def test_deserialize_many_with_related_field(self):
        """Test deserializing multiple items with foreign key relations"""
        serializer_wrapper = DRFDynamicSerializer()
        fields_map = {
            self.dummy_model_name: {"name", "value", "related"}
        }

        input_data = [
            {"name": "Item1", "value": 10, "related": self.related.pk},
            {"name": "Item2", "value": 20, "related": self.related.pk}
        ]

        validated_data = serializer_wrapper.deserialize(
            DummyModel,
            input_data,
            fields_map=fields_map,
            many=True
        )

        # Check that relations are preserved
        self.assertEqual(len(validated_data), 2)
        self.assertEqual(validated_data[0]["related"], self.related)
        self.assertEqual(validated_data[1]["related"], self.related)


class BulkCreateEndToEndTests(TestCase):
    """Test the complete bulk_create flow through AST parser"""

    def setUp(self):
        self.related = DummyRelatedModel.objects.create(name="Related")
        self.dummy_model_name = config.orm_provider.get_model_name(DummyModel)

    def test_bulk_create_via_ast_parser(self):
        """Test bulk_create through the full AST parser flow"""
        # Create a mock request
        mock_request = Mock()

        # Build the AST for bulk_create
        ast = {
            "type": "bulk_create",
            "data": [
                {"name": "Bulk Item 1", "value": 100},
                {"name": "Bulk Item 2", "value": 200},
                {"name": "Bulk Item 3", "value": 300}
            ]
        }

        # Create the AST parser
        parser = ASTParser(
            engine=config.orm_provider,
            serializer=config.serializer,
            model=DummyModel,
            config=config,
            registry=registry,
            base_queryset=DummyModel.objects.all(),
            serializer_options={"fields": ["name", "value"]},
            request=mock_request
        )

        # Parse the AST
        result = parser.parse(ast)

        # Verify the result structure
        self.assertIn("data", result)
        self.assertIn("metadata", result)

        # Check metadata
        self.assertTrue(result["metadata"]["created"])
        self.assertEqual(result["metadata"]["response_type"], "queryset")

        # Verify data was returned (serialized format)
        self.assertIn("data", result["data"])
        self.assertIn("included", result["data"])
        self.assertEqual(len(result["data"]["data"]), 3)

        # Verify items were actually created in the database
        created_items = DummyModel.objects.filter(name__startswith="Bulk Item")
        self.assertEqual(created_items.count(), 3)

        # Verify each item has correct data
        item1 = DummyModel.objects.get(name="Bulk Item 1")
        self.assertEqual(item1.value, 100)

        item2 = DummyModel.objects.get(name="Bulk Item 2")
        self.assertEqual(item2.value, 200)

        item3 = DummyModel.objects.get(name="Bulk Item 3")
        self.assertEqual(item3.value, 300)

    def test_bulk_create_with_foreign_keys(self):
        """Test bulk_create with foreign key relationships"""
        mock_request = Mock()

        ast = {
            "type": "bulk_create",
            "data": [
                {"name": "Item 1", "value": 10, "related": self.related.pk},
                {"name": "Item 2", "value": 20, "related": self.related.pk}
            ]
        }

        parser = ASTParser(
            engine=config.orm_provider,
            serializer=config.serializer,
            model=DummyModel,
            config=config,
            registry=registry,
            base_queryset=DummyModel.objects.all(),
            serializer_options={"fields": ["name", "value", "related"]},
            request=mock_request
        )

        result = parser.parse(ast)

        # Verify creation
        self.assertTrue(result["metadata"]["created"])

        # Verify foreign keys were set correctly
        item1 = DummyModel.objects.get(name="Item 1")
        self.assertEqual(item1.related, self.related)

        item2 = DummyModel.objects.get(name="Item 2")
        self.assertEqual(item2.related, self.related)


if __name__ == "__main__":
    import unittest
    unittest.main()
