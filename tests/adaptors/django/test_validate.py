# tests/adaptors/django/test_validate.py

import json
from decimal import Decimal
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from tests.django_app.models import (
    DummyModel,
    DummyRelatedModel,
    ComprehensiveModel,
    DeepModelLevel1,
    DeepModelLevel2,
    DeepModelLevel3,
    Product,
    ProductCategory,
)


class ValidateEndpointTest(APITestCase):
    """Test the validate endpoint for fast validation without saving."""

    def setUp(self):
        # Create and log in a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create related model instances for testing
        self.related_dummy = DummyRelatedModel.objects.create(name="TestRelated")

        # Create category for product tests
        self.category = ProductCategory.objects.create(name="Electronics")

    def test_validate_create_valid_data(self):
        """Test validation with valid data for creation."""
        url = reverse("statezero:validate", args=["django_app.DummyModel"])
        payload = {
            "data": {
                "name": "ValidTest",
                "value": 100,
                "related": self.related_dummy.id,
            },
            "validate_type": "create",
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"valid": True})

    def test_validate_create_invalid_data(self):
        """Test validation with invalid data for creation."""
        url = reverse("statezero:validate", args=["django_app.DummyModel"])
        payload = {
            "data": {
                "name": "",  # Invalid: empty name (blank=False by default)
                "value": "not_a_number",  # Invalid: string instead of int
                "related": 99999,  # Invalid: non-existent related object
            },
            "validate_type": "create",
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["type"], "ValidationError")

    def test_validate_missing_required_fields(self):
        """Test validation fails when required fields are missing."""
        # DummyModel: name is required, value has default=0, related has null=True
        url = reverse("statezero:validate", args=["django_app.DummyModel"])
        payload = {"data": {}}  # Missing required name field

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["type"], "ValidationError")

    def test_validate_comprehensive_model(self):
        """Test validation with ComprehensiveModel."""
        # Create required related object
        level3 = DeepModelLevel3.objects.create(name="Level3")
        level2 = DeepModelLevel2.objects.create(name="Level2", level3=level3)
        level1 = DeepModelLevel1.objects.create(name="Level1", level2=level2)

        url = reverse("statezero:validate", args=["django_app.ComprehensiveModel"])
        payload = {
            "data": {
                "char_field": "TestChar",
                "text_field": "Test text content",
                "int_field": 42,
                "bool_field": True,
                "decimal_field": "123.45",
                "json_field": {"key": "value"},
                "money_field": {"amount": "99.99", "currency": "USD"},
                "related": level1.id,
            },
            "validate_type": "create",
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"valid": True})

    def test_validate_comprehensive_model_missing_required(self):
        """ComprehensiveModel has several required fields with no defaults."""
        url = reverse("statezero:validate", args=["django_app.ComprehensiveModel"])
        payload = {
            "data": {
                "char_field": "TestChar"
                # Missing: text_field, int_field (no defaults)
            }
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["type"], "ValidationError")

    def test_validate_money_field_invalid_format(self):
        """Money field requires object with amount and currency."""
        level3 = DeepModelLevel3.objects.create(name="Level3")
        level2 = DeepModelLevel2.objects.create(name="Level2", level3=level3)
        level1 = DeepModelLevel1.objects.create(name="Level1", level2=level2)

        url = reverse("statezero:validate", args=["django_app.ComprehensiveModel"])
        payload = {
            "data": {
                "char_field": "TestChar",
                "text_field": "Test text",
                "int_field": 42,
                "money_field": "99.99",  # Wrong format - should be object
                "related": level1.id,
            }
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["type"], "ValidationError")

    def test_validate_product_model(self):
        """Product has required fields: name, description, price, category."""
        url = reverse("statezero:validate", args=["django_app.Product"])
        payload = {
            "data": {
                "name": "Test Product",
                "description": "A test product description",
                "price": "29.99",
                "category": self.category.id,
                # in_stock has default=True, created_at has default, created_by has null=True
            }
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"valid": True})

    def test_validate_foreign_key_validation(self):
        """Test validation catches invalid foreign keys."""
        url = reverse("statezero:validate", args=["django_app.DummyModel"])
        payload = {
            "data": {
                "name": "FKTest",
                "value": 100,
                "related": 99999,  # Non-existent related object
            }
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["type"], "ValidationError")

    def test_validate_nonexistent_model(self):
        """Test validation with non-existent model."""
        url = reverse("statezero:validate", args=["django_app.NonExistentModel"])
        payload = {"data": {"name": "test"}}

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 500)  # LookupError gets mapped to 500

    def test_validate_empty_data_with_defaults(self):
        """DummyModel: name required, value has default=0, related nullable."""
        url = reverse("statezero:validate", args=["django_app.DummyModel"])
        payload = {"data": {}}

        response = self.client.post(url, data=payload, format="json")

        # Should fail because name is required
        self.assertEqual(response.status_code, 400)

    def test_validate_partial_update(self):
        """Updates should allow partial data."""
        url = reverse("statezero:validate", args=["django_app.DummyModel"])
        payload = {"data": {"value": 999}, "validate_type": "update", "partial": True}

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"valid": True})

    def test_validate_no_database_side_effects(self):
        """Validation should not create database records."""
        initial_count = DummyModel.objects.count()

        url = reverse("statezero:validate", args=["django_app.DummyModel"])
        payload = {
            "data": {
                "name": "ShouldNotBeSaved",
                "value": 100,
                "related": self.related_dummy.id,
            }
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)

        # Verify no new records were created
        final_count = DummyModel.objects.count()
        self.assertEqual(initial_count, final_count)

    def test_validate_malformed_json(self):
        """Test with invalid JSON."""
        url = reverse("statezero:validate", args=["django_app.DummyModel"])

        response = self.client.post(
            url, data="invalid_json", content_type="application/json"
        )

        self.assertEqual(response.status_code, 400)

    def test_validate_missing_name_field_dummymodel(self):
        """DummyModel requires name field."""
        url = reverse("statezero:validate", args=["django_app.DummyModel"])
        payload = {
            "data": {
                "value": 100,
                "related": self.related_dummy.id,
                # Missing required name field
            }
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["type"], "ValidationError")
