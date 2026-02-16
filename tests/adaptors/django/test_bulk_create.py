from django.test import TestCase
from unittest.mock import Mock

from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.serializers import DRFDynamicSerializer
from statezero.adaptors.django.ast_parser import ASTParser
from tests.django_app.models import DummyModel, DummyRelatedModel, Order


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

    def test_bulk_create_with_hooks(self):
        """Test bulk_create with pre and post hooks using Order model"""
        mock_request = Mock()

        # Order model has:
        # - pre_hooks=[normalize_email] - normalizes email to lowercase/stripped
        # - post_hooks=[generate_order_number] - generates order number if not provided or if it's DUMMY

        ast = {
            "type": "bulk_create",
            "data": [
                {
                    "customer_name": "John Doe",
                    "customer_email": "  JOHN@EXAMPLE.COM  ",  # Should be normalized to lowercase and stripped
                    "order_number": "ORD-BULK-001",  # Valid order number, won't trigger post-hook
                    "total": "100.00"
                },
                {
                    "customer_name": "Jane Smith",
                    "customer_email": "JANE@TEST.COM",  # Should be normalized
                    "order_number": "ORD-BULK-002",  # Valid order number, won't trigger post-hook
                    "total": "200.00"
                },
                {
                    "customer_name": "Bob Wilson",
                    "customer_email": "  BOB@EXAMPLE.COM",  # Should be normalized
                    "order_number": "ORD-BULK-003",  # Valid order number, won't trigger post-hook
                    "total": "150.00"
                }
            ]
        }

        order_model_name = config.orm_provider.get_model_name(Order)
        parser = ASTParser(
            engine=config.orm_provider,
            serializer=config.serializer,
            model=Order,
            config=config,
            registry=registry,
            base_queryset=Order.objects.all(),
            serializer_options={"fields": ["customer_name", "customer_email", "order_number", "total"]},
            request=mock_request
        )

        result = parser.parse(ast)

        # Verify creation
        self.assertTrue(result["metadata"]["created"])

        # Verify items were created
        created_orders = Order.objects.filter(customer_name__in=["John Doe", "Jane Smith", "Bob Wilson"])
        self.assertEqual(created_orders.count(), 3)

        # Verify pre-hook (normalize_email) worked
        john_order = Order.objects.get(customer_name="John Doe")
        self.assertEqual(john_order.customer_email, "john@example.com")  # Normalized

        jane_order = Order.objects.get(customer_name="Jane Smith")
        self.assertEqual(jane_order.customer_email, "jane@test.com")  # Normalized

        bob_order = Order.objects.get(customer_name="Bob Wilson")
        self.assertEqual(bob_order.customer_email, "bob@example.com")  # Normalized

        # Verify order numbers were preserved (no DUMMY in them, so post-hook didn't change them)
        self.assertEqual(john_order.order_number, "ORD-BULK-001")
        self.assertEqual(jane_order.order_number, "ORD-BULK-002")
        self.assertEqual(bob_order.order_number, "ORD-BULK-003")

        # Verify all order numbers are unique (important for bulk operations)
        order_numbers = {john_order.order_number, jane_order.order_number, bob_order.order_number}
        self.assertEqual(len(order_numbers), 3, "All order numbers should be unique")


    def test_bulk_create_with_dummy_order_numbers(self):
        """Test that post-hook generates unique order numbers for DUMMY values in bulk operations"""
        mock_request = Mock()

        ast = {
            "type": "bulk_create",
            "data": [
                {
                    "customer_name": "Test Order 1",
                    "customer_email": "test1@example.com",
                    "order_number": "DUMMY-1",  # Should be replaced with unique UUID-based number
                    "total": "100.00"
                },
                {
                    "customer_name": "Test Order 2",
                    "customer_email": "test2@example.com",
                    "order_number": "DUMMY-2",  # Should be replaced with unique UUID-based number
                    "total": "200.00"
                },
                {
                    "customer_name": "Test Order 3",
                    "customer_email": "test3@example.com",
                    "order_number": "DUMMY-3",  # Should be replaced with unique UUID-based number
                    "total": "150.00"
                }
            ]
        }

        parser = ASTParser(
            engine=config.orm_provider,
            serializer=config.serializer,
            model=Order,
            config=config,
            registry=registry,
            base_queryset=Order.objects.all(),
            serializer_options={"fields": ["customer_name", "customer_email", "order_number", "total"]},
            request=mock_request
        )

        result = parser.parse(ast)

        # Verify creation
        self.assertTrue(result["metadata"]["created"])

        # Verify items were created
        created_orders = Order.objects.filter(customer_name__startswith="Test Order")
        self.assertEqual(created_orders.count(), 3)

        # Get all the orders
        order1 = Order.objects.get(customer_name="Test Order 1")
        order2 = Order.objects.get(customer_name="Test Order 2")
        order3 = Order.objects.get(customer_name="Test Order 3")

        # Verify post-hook replaced DUMMY values with ORD- prefixed numbers
        self.assertTrue(order1.order_number.startswith("ORD-"))
        self.assertNotIn("DUMMY", order1.order_number)

        self.assertTrue(order2.order_number.startswith("ORD-"))
        self.assertNotIn("DUMMY", order2.order_number)

        self.assertTrue(order3.order_number.startswith("ORD-"))
        self.assertNotIn("DUMMY", order3.order_number)

        # CRITICAL: Verify all order numbers are unique (no duplicates)
        order_numbers = {order1.order_number, order2.order_number, order3.order_number}
        self.assertEqual(len(order_numbers), 3, "All generated order numbers must be unique")


if __name__ == "__main__":
    import unittest
    unittest.main()
