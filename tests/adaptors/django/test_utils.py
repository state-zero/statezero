"""
Tests for the public utility functions in statezero.adaptors.django.utils.

These tests verify that generate_schema and generate_serializer_class work
correctly for models that are not registered with StateZero.
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

from decimal import Decimal
from django.test import TestCase
from django.db import models

from statezero.adaptors.django.utils import generate_schema, generate_serializer_class
from statezero.adaptors.django.config import config
from statezero.core.config import ModelConfig
from statezero.core.classes import (
    AdditionalField,
    FieldFormat,
    FieldType,
    ModelSchemaMetadata,
)

# Test models - these are NOT registered with StateZero
from tests.django_app.models import Product, ProductCategory, Order, OrderItem


class TestGenerateSchemaUnregistered(TestCase):
    """Test generate_schema with explicit ModelConfig."""

    def test_basic_schema_generation(self):
        """Should generate schema using provided ModelConfig."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            filterable_fields="__all__",
            searchable_fields=set(),
            ordering_fields="__all__",
        )

        schema = generate_schema(Product, my_config)

        self.assertIsInstance(schema, ModelSchemaMetadata)
        self.assertEqual(schema.class_name, "Product")
        self.assertIn("name", schema.properties)
        self.assertIn("price", schema.properties)
        self.assertIn("category", schema.properties)

    def test_schema_respects_fields_config(self):
        """Should only include fields specified in ModelConfig.fields."""
        my_config = ModelConfig(
            model=Product,
            fields={"name", "price"},
            filterable_fields=set(),
            searchable_fields=set(),
            ordering_fields=set(),
        )

        schema = generate_schema(Product, my_config)

        self.assertIn("name", schema.properties)
        self.assertIn("price", schema.properties)
        # id is always included as primary key
        self.assertIn("id", schema.properties)
        # category should NOT be included
        self.assertNotIn("category", schema.properties)
        self.assertNotIn("description", schema.properties)

    def test_schema_with_additional_fields(self):
        """Should include additional computed fields from ModelConfig."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            filterable_fields="__all__",
            searchable_fields=set(),
            ordering_fields="__all__",
            additional_fields=[
                AdditionalField(
                    name="computed_value",
                    field=models.CharField(max_length=100),
                    title="Computed Value",
                )
            ],
        )

        schema = generate_schema(Product, my_config)

        self.assertIn("computed_value", schema.properties)
        computed_field = schema.properties["computed_value"]
        self.assertTrue(computed_field.read_only)
        self.assertEqual(computed_field.title, "Computed Value")

    def test_schema_filterable_fields(self):
        """Should set filterable_fields from ModelConfig."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            filterable_fields={"name", "price"},
            searchable_fields=set(),
            ordering_fields=set(),
        )

        schema = generate_schema(Product, my_config)

        self.assertEqual(schema.filterable_fields, {"name", "price"})

    def test_schema_searchable_fields(self):
        """Should set searchable_fields from ModelConfig."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            filterable_fields=set(),
            searchable_fields={"name", "description"},
            ordering_fields=set(),
        )

        schema = generate_schema(Product, my_config)

        self.assertEqual(schema.searchable_fields, {"name", "description"})

    def test_schema_ordering_fields(self):
        """Should set ordering_fields from ModelConfig."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            filterable_fields=set(),
            searchable_fields=set(),
            ordering_fields={"name", "created_at"},
        )

        schema = generate_schema(Product, my_config)

        self.assertEqual(schema.ordering_fields, {"name", "created_at"})

    def test_schema_respects_schema_overrides(self):
        """Should use config.schema_overrides for custom field types like MoneyField."""
        from tests.django_app.models import ComprehensiveModel
        from djmoney.models.fields import MoneyField

        # Verify that schema_overrides has MoneyField configured
        self.assertIn(MoneyField, config.schema_overrides)

        my_config = ModelConfig(
            model=ComprehensiveModel,
            fields="__all__",
            filterable_fields="__all__",
            searchable_fields=set(),
            ordering_fields="__all__",
        )

        schema = generate_schema(ComprehensiveModel, my_config)

        # ComprehensiveModel.money_field is a MoneyField - should have MONEY format
        # This proves config.schema_overrides is being used
        self.assertIn("money_field", schema.properties)
        money_field = schema.properties["money_field"]
        self.assertEqual(money_field.format, FieldFormat.MONEY)

        # Also verify the $ref is set (MoneyField schema override adds a definition)
        self.assertIsNotNone(money_field.ref)

    def test_schema_relationships(self):
        """Should include relationship metadata."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            filterable_fields="__all__",
            searchable_fields=set(),
            ordering_fields="__all__",
        )

        schema = generate_schema(Product, my_config)

        self.assertIn("category", schema.relationships)
        rel = schema.relationships["category"]
        self.assertEqual(rel["type"], FieldFormat.FOREIGN_KEY)
        self.assertEqual(rel["class_name"], "ProductCategory")

    def test_schema_with_allowed_fields_filter(self):
        """Should filter properties based on allowed_fields parameter."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            filterable_fields="__all__",
            searchable_fields=set(),
            ordering_fields="__all__",
        )

        schema = generate_schema(Product, my_config, allowed_fields={"id", "name"})

        self.assertIn("id", schema.properties)
        self.assertIn("name", schema.properties)
        self.assertNotIn("price", schema.properties)
        self.assertNotIn("category", schema.properties)


class TestGenerateSerializerClassUnregistered(TestCase):
    """Test generate_serializer_class with explicit ModelConfig."""

    def setUp(self):
        self.category = ProductCategory.objects.create(name="Test Category")
        self.product = Product.objects.create(
            name="Test Product",
            description="A test product",
            price="99.99",
            category=self.category,
        )

    def tearDown(self):
        Product.objects.all().delete()
        ProductCategory.objects.all().delete()

    def test_basic_serializer_generation(self):
        """Should create a working serializer class."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
        )

        SerializerClass = generate_serializer_class(Product, my_config)
        serializer = SerializerClass(self.product)
        data = serializer.data

        self.assertIn("id", data)
        self.assertIn("name", data)
        self.assertEqual(data["name"], "Test Product")
        self.assertIn("repr", data)

    def test_serializer_respects_fields_param(self):
        """Should only include specified fields."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
        )

        SerializerClass = generate_serializer_class(
            Product, my_config, fields={"id", "name"}
        )
        serializer = SerializerClass(self.product)
        data = serializer.data

        self.assertIn("id", data)
        self.assertIn("name", data)
        self.assertIn("repr", data)  # Always included
        # price should not be included
        self.assertNotIn("price", data)

    def test_serializer_with_additional_fields(self):
        """Should include additional computed fields from ModelConfig."""
        # Add a property to Product for testing
        Product.computed_value = property(lambda self: f"computed_{self.name}")

        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            additional_fields=[
                AdditionalField(
                    name="computed_value",
                    field=models.CharField(max_length=100),
                    title="Computed Value",
                )
            ],
        )

        SerializerClass = generate_serializer_class(Product, my_config)
        serializer = SerializerClass(self.product)
        data = serializer.data

        self.assertIn("computed_value", data)
        self.assertEqual(data["computed_value"], "computed_Test Product")

        # Cleanup
        del Product.computed_value

    def test_serializer_respects_custom_serializers(self):
        """Should use config.custom_serializers for custom field types like MoneyField."""
        from tests.django_app.models import ComprehensiveModel
        from djmoney.models.fields import MoneyField

        # Verify that custom_serializers has MoneyField configured
        self.assertIn(MoneyField, config.custom_serializers)

        # Create a ComprehensiveModel instance with a money value
        comprehensive = ComprehensiveModel.objects.create(
            char_field="test",
            text_field="test text",
            int_field=1,
            bool_field=True,
            decimal_field="10.00",
            money_field_currency="USD",
        )

        my_config = ModelConfig(
            model=ComprehensiveModel,
            fields="__all__",
        )

        SerializerClass = generate_serializer_class(ComprehensiveModel, my_config)
        serializer = SerializerClass(comprehensive)
        data = serializer.data

        # MoneyField should be serialized using custom serializer
        # The MoneyFieldSerializer returns a dict with 'amount' and 'currency'
        self.assertIn("money_field", data)
        money_data = data["money_field"]
        self.assertIsInstance(money_data, dict)
        self.assertIn("amount", money_data)
        self.assertIn("currency", money_data)
        self.assertEqual(money_data["currency"], "USD")

        # Cleanup
        comprehensive.delete()

    def test_serializer_handles_foreign_key(self):
        """Should serialize foreign key as primary key."""
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
        )

        SerializerClass = generate_serializer_class(Product, my_config)
        serializer = SerializerClass(self.product)
        data = serializer.data

        self.assertIn("category", data)
        self.assertEqual(data["category"], self.category.pk)

    def test_serializer_handles_many_instances(self):
        """Should work with many=True for querysets."""
        Product.objects.create(
            name="Product 2",
            description="Another product",
            price="49.99",
            category=self.category,
        )

        my_config = ModelConfig(
            model=Product,
            fields="__all__",
        )

        SerializerClass = generate_serializer_class(Product, my_config)
        products = Product.objects.all()
        serializer = SerializerClass(products, many=True)
        data = serializer.data

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "Test Product")
        self.assertEqual(data[1]["name"], "Product 2")


class TestUtilsIgnoreRegistry(TestCase):
    """Test that utils ignore the registry even for registered models."""

    def setUp(self):
        self.category = ProductCategory.objects.create(name="Test Category")
        self.product = Product.objects.create(
            name="Test Product",
            description="A test product",
            price="99.99",
            category=self.category,
        )

    def tearDown(self):
        Product.objects.all().delete()
        ProductCategory.objects.all().delete()

    def test_schema_uses_provided_config_not_registry(self):
        """Should use provided ModelConfig even if model is registered."""
        from statezero.adaptors.django.config import registry

        # Verify Product IS registered
        registered_config = registry.get_config(Product)
        self.assertIsNotNone(registered_config)

        # The registered config has more fields than what we'll provide
        # We provide a config with only "name" field
        my_config = ModelConfig(
            model=Product,
            fields={"name"},  # Only name field
            filterable_fields=set(),
            searchable_fields=set(),
            ordering_fields=set(),
        )

        schema = generate_schema(Product, my_config)

        # Should only have name (plus id as PK)
        self.assertIn("name", schema.properties)
        self.assertIn("id", schema.properties)
        # Should NOT have other fields even though registered config has them
        self.assertNotIn("description", schema.properties)
        self.assertNotIn("category", schema.properties)
        self.assertNotIn("price", schema.properties)

        # Verify filterable_fields uses OUR config (empty), not registry's
        self.assertEqual(schema.filterable_fields, set())

    def test_serializer_uses_provided_config_not_registry(self):
        """Should use provided ModelConfig even if model is registered."""
        from statezero.adaptors.django.config import registry

        # Verify Product IS registered
        registered_config = registry.get_config(Product)
        self.assertIsNotNone(registered_config)

        my_config = ModelConfig(
            model=Product,
            fields={"name"},
        )

        SerializerClass = generate_serializer_class(
            Product, my_config, fields={"id", "name"}
        )
        serializer = SerializerClass(self.product)
        data = serializer.data

        self.assertIn("name", data)
        self.assertIn("id", data)
        self.assertIn("repr", data)
        # Should NOT have other fields even though model is registered with more
        self.assertNotIn("description", data)
        self.assertNotIn("price", data)
        self.assertNotIn("category", data)

    def test_schema_different_filterable_fields_than_registry(self):
        """Filterable fields should come from provided config, not registry."""
        from statezero.adaptors.django.config import registry

        registered_config = registry.get_config(Product)
        # Registry likely has filterable_fields set

        # Our config has completely different filterable_fields
        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            filterable_fields={"name", "description"},  # Only these two
            searchable_fields={"name"},
            ordering_fields={"id"},
        )

        schema = generate_schema(Product, my_config)

        # Should use OUR filterable_fields, not the registry's
        self.assertEqual(schema.filterable_fields, {"name", "description"})
        self.assertEqual(schema.searchable_fields, {"name"})
        self.assertEqual(schema.ordering_fields, {"id"})

    def test_schema_with_different_additional_fields_than_registry(self):
        """Additional fields should come from provided config, not registry."""
        from statezero.adaptors.django.config import registry

        registered_config = registry.get_config(Product)

        # Add a custom computed field that's NOT in the registry config
        Product.my_custom_computed = property(lambda self: f"custom_{self.id}")

        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            filterable_fields="__all__",
            additional_fields=[
                AdditionalField(
                    name="my_custom_computed",
                    field=models.CharField(max_length=50),
                    title="My Custom Field",
                )
            ],
        )

        schema = generate_schema(Product, my_config)

        # Should have OUR additional field
        self.assertIn("my_custom_computed", schema.properties)
        self.assertEqual(schema.properties["my_custom_computed"].title, "My Custom Field")

        # Cleanup
        del Product.my_custom_computed

    def test_serializer_with_different_additional_fields_than_registry(self):
        """Serializer additional fields should come from provided config."""
        from statezero.adaptors.django.config import registry

        registered_config = registry.get_config(Product)

        # Add a custom computed field
        Product.my_serializer_field = property(lambda self: f"serialized_{self.name}")

        my_config = ModelConfig(
            model=Product,
            fields="__all__",
            additional_fields=[
                AdditionalField(
                    name="my_serializer_field",
                    field=models.CharField(max_length=100),
                    title="My Serializer Field",
                )
            ],
        )

        SerializerClass = generate_serializer_class(Product, my_config)
        serializer = SerializerClass(self.product)
        data = serializer.data

        # Should have OUR additional field
        self.assertIn("my_serializer_field", data)
        self.assertEqual(data["my_serializer_field"], "serialized_Test Product")

        # Cleanup
        del Product.my_serializer_field
