"""
Tests for reverse relationship handling in StateZero.

Reverse relationships (ForeignObjectRel) should:
1. Only be included if explicitly declared in model config's `fields`
2. Be treated as read-only (cannot be written to directly)
3. Use M2M format for ManyToOneRel (reverse FK) and ManyToManyRel
4. Use FK format for OneToOneRel (reverse O2O)
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from tests.django_app.models import Order, OrderItem, Product, ProductCategory
from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.schemas import DjangoSchemaGenerator
from statezero.adaptors.django.serializers import DynamicModelSerializer, fields_map_context
from statezero.core.classes import FieldType, FieldFormat

User = get_user_model()


class TestReverseRelationshipSchema(TestCase):
    """Test that reverse relationships are correctly represented in the schema."""

    def setUp(self):
        self.schema_generator = DjangoSchemaGenerator()

    def test_reverse_fk_included_in_schema_when_declared(self):
        """Order.items (reverse FK from OrderItem) should be in schema when declared."""
        schema = self.schema_generator.generate_schema(
            model=Order,
            global_schema_overrides=config.schema_overrides,
            additional_fields=[],
        )

        # 'items' should be in properties
        self.assertIn("items", schema.properties)

        # Should be array type with M2M format (like a M2M field)
        items_schema = schema.properties["items"]
        self.assertEqual(items_schema.type, FieldType.ARRAY)
        self.assertEqual(items_schema.format, FieldFormat.MANY_TO_MANY)
        self.assertTrue(items_schema.read_only)

    def test_reverse_fk_in_relationships(self):
        """Order.items should be recorded in relationships dict."""
        schema = self.schema_generator.generate_schema(
            model=Order,
            global_schema_overrides=config.schema_overrides,
            additional_fields=[],
        )

        self.assertIn("items", schema.relationships)
        rel_info = schema.relationships["items"]
        self.assertEqual(rel_info["type"], FieldFormat.MANY_TO_MANY)
        self.assertEqual(rel_info["class_name"], "OrderItem")

    def test_reverse_relation_not_included_when_fields_is_all(self):
        """Models with fields='__all__' should NOT auto-include reverse relations."""
        # ProductCategory uses __all__ for fields (default)
        schema = self.schema_generator.generate_schema(
            model=ProductCategory,
            global_schema_overrides=config.schema_overrides,
            additional_fields=[],
        )

        # 'products' is a reverse relation but should NOT be included
        # because ProductCategory doesn't explicitly declare it in fields
        self.assertNotIn("products", schema.properties)

    def test_reverse_relation_is_read_only(self):
        """Reverse relations should always be marked as read_only."""
        schema = self.schema_generator.generate_schema(
            model=Order,
            global_schema_overrides=config.schema_overrides,
            additional_fields=[],
        )

        items_schema = schema.properties["items"]
        self.assertTrue(items_schema.read_only)


class TestReverseRelationshipSerializer(TestCase):
    """Test that reverse relationships are correctly serialized."""

    def setUp(self):
        # Create test data
        self.category = ProductCategory.objects.create(name="Electronics")
        self.product = Product.objects.create(
            name="Laptop",
            description="A laptop",
            price="999.99",
            category=self.category,
        )
        self.order = Order.objects.create(
            order_number="ORD-001",
            customer_name="John Doe",
            customer_email="john@example.com",
            total="1999.98",
            status="pending",
        )
        self.order_item1 = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            price="999.99",
        )
        self.order_item2 = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            price="999.99",
        )

    def test_reverse_relation_serializes_pks(self):
        """Reverse relation should serialize as list of primary keys."""
        model_name = config.orm_provider.get_model_name(Order)
        fields_map = {
            model_name: {"id", "order_number", "items", "repr"}
        }

        with fields_map_context(fields_map):
            serializer_class = DynamicModelSerializer.for_model(Order)
            serializer = serializer_class(self.order)
            data = serializer.data

        # 'items' should be a list of PKs
        self.assertIn("items", data)
        self.assertIsInstance(data["items"], list)
        self.assertEqual(len(data["items"]), 2)
        self.assertIn(self.order_item1.pk, data["items"])
        self.assertIn(self.order_item2.pk, data["items"])

    def test_reverse_relation_not_in_serializer_when_not_declared(self):
        """Reverse relation should not appear if not in model config fields."""
        model_name = config.orm_provider.get_model_name(ProductCategory)
        # Even if we request 'products' in fields_map, it shouldn't be included
        # because ProductCategory doesn't declare it in its model config
        fields_map = {
            model_name: {"id", "name", "products", "repr"}
        }

        with fields_map_context(fields_map):
            serializer_class = DynamicModelSerializer.for_model(ProductCategory)
            serializer = serializer_class(self.category)
            data = serializer.data

        # 'products' should NOT be in the output
        self.assertNotIn("products", data)

    def test_reverse_relation_is_read_only_in_serializer(self):
        """Attempting to write to a reverse relation should be ignored."""
        model_name = config.orm_provider.get_model_name(Order)
        fields_map = {
            model_name: {"id", "order_number", "items", "repr"}
        }

        with fields_map_context(fields_map):
            serializer_class = DynamicModelSerializer.for_model(Order)
            # Try to set 'items' - should be ignored since it's read-only
            serializer = serializer_class(
                self.order,
                data={"items": [999]},  # Try to set invalid items
                partial=True
            )
            # Validation should pass (read-only fields are ignored)
            self.assertTrue(serializer.is_valid())
            # 'items' should not be in validated_data
            self.assertNotIn("items", serializer.validated_data)


class TestReverseRelationshipIntegration(TestCase):
    """Integration tests for reverse relationships through the full pipeline."""

    def setUp(self):
        self.category = ProductCategory.objects.create(name="Books")
        self.product = Product.objects.create(
            name="Python Guide",
            description="A book about Python",
            price="49.99",
            category=self.category,
        )
        self.order = Order.objects.create(
            order_number="ORD-002",
            customer_name="Jane Smith",
            customer_email="jane@example.com",
            total="99.98",
        )
        self.item1 = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            price="49.99",
        )

    def test_full_serialization_with_reverse_relation(self):
        """Test full serialization pipeline includes reverse relations correctly."""
        from statezero.adaptors.django.serializers import DRFDynamicSerializer

        serializer = DRFDynamicSerializer()
        model_name = config.orm_provider.get_model_name(Order)
        order_item_model_name = config.orm_provider.get_model_name(OrderItem)

        fields_map = {
            model_name: {"id", "order_number", "customer_name", "items"},
            order_item_model_name: {"id", "quantity", "price"},
            "requested-fields::": ["id", "order_number", "customer_name", "items"]
        }

        result = serializer.serialize(
            data=self.order,
            model=Order,
            depth=0,
            fields_map=fields_map,
            many=False,
        )

        # Check top-level data
        self.assertIn("data", result)
        self.assertEqual(result["data"], [self.order.pk])

        # Check included has the order with items
        self.assertIn("included", result)
        self.assertIn(model_name, result["included"])

        order_data = result["included"][model_name][self.order.pk]
        self.assertIn("items", order_data)
        self.assertEqual(order_data["items"], [self.item1.pk])


class TestReverseRelationshipAPIIntegration(APITestCase):
    """API integration tests for reverse relationships via DRF mock API calls."""

    def setUp(self):
        # Create a test user and authenticate
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.force_authenticate(user=self.user)

        # Create test data
        self.category = ProductCategory.objects.create(name="Electronics")
        self.product = Product.objects.create(
            name="Laptop",
            description="A laptop",
            price="999.99",
            category=self.category,
        )
        self.order = Order.objects.create(
            order_number="ORD-API-001",
            customer_name="API User",
            customer_email="api@example.com",
            total="2999.97",
            status="pending",
        )
        self.item1 = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            price="999.99",
        )
        self.item2 = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            price="999.99",
        )

    def test_api_query_order_with_items_reverse_relation(self):
        """Test querying Order via API includes items reverse relationship."""
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.order.pk}
                    },
                },
                "serializerOptions": {
                    "fields": ["id", "order_number", "customer_name", "items"],
                },
            }
        }

        url = reverse("statezero:model_view", args=["django_app.Order"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)

        # Response is nested: response.data contains {data: [...], included: {...}}
        response_data = response.data.get("data", {})

        # Check the response structure - data.data is a list of PKs
        data = response_data.get("data", [])
        self.assertIn(self.order.pk, data)

        # Check included contains the order with items
        included = response_data.get("included", {})
        self.assertIn("django_app.order", included)

        order_data = included["django_app.order"].get(self.order.pk)
        self.assertIsNotNone(order_data)
        self.assertIn("items", order_data)

        # Items should be a list of PKs
        items = order_data["items"]
        self.assertIsInstance(items, list)
        self.assertEqual(len(items), 2)
        self.assertIn(self.item1.pk, items)
        self.assertIn(self.item2.pk, items)

    def test_api_reverse_relation_is_read_only(self):
        """Test that attempting to write to items via API is ignored."""
        # Try to update the order with items - should be ignored
        payload = {
            "ast": {
                "query": {
                    "type": "update",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.order.pk}
                    },
                    "data": {
                        "customer_name": "Updated Name",
                        "items": [999, 998]  # Try to set items - should be ignored
                    }
                },
            }
        }

        url = reverse("statezero:model_view", args=["django_app.Order"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)

        # Verify the order was updated
        self.order.refresh_from_db()
        self.assertEqual(self.order.customer_name, "Updated Name")

        # Verify items are still the original ones (not changed)
        current_items = list(self.order.items.values_list("pk", flat=True))
        self.assertEqual(len(current_items), 2)
        self.assertIn(self.item1.pk, current_items)
        self.assertIn(self.item2.pk, current_items)
