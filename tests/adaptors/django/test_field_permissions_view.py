import json

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from statezero.adaptors.django.permissions import AllowAllPermission
from statezero.core.types import ActionType
from tests.django_app.models import DummyModel, DummyRelatedModel, CustomPKModel


class FieldPermissionsViewTest(APITestCase):
    def setUp(self):
        # Create and log in a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create test models
        self.related_dummy = DummyRelatedModel.objects.create(name="Related1")
        self.dummy = DummyModel.objects.create(
            name="TestDummy", value=100, related=self.related_dummy
        )

    def test_field_permissions_endpoint_returns_all_permission_types(self):
        """Test that the field permissions endpoint returns visible, creatable, and editable fields."""
        url = reverse("statezero:field_permissions", args=["django_app.DummyModel"])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200, f"Failed with response: {response.data}")

        # Check that all three field types are present
        self.assertIn("visible_fields", response.data)
        self.assertIn("creatable_fields", response.data)
        self.assertIn("editable_fields", response.data)

        # Check that fields are returned as lists
        self.assertIsInstance(response.data["visible_fields"], list)
        self.assertIsInstance(response.data["creatable_fields"], list)
        self.assertIsInstance(response.data["editable_fields"], list)

    def test_field_permissions_with_allow_all_permission(self):
        """Test field permissions with AllowAllPermission returns all fields."""
        url = reverse("statezero:field_permissions", args=["django_app.DummyModel"])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        # With AllowAllPermission, all fields should be visible, creatable, and editable
        # (subject to frontend_fields constraint for visible)
        self.assertGreater(len(response.data["visible_fields"]), 0)
        self.assertGreater(len(response.data["creatable_fields"]), 0)
        self.assertGreater(len(response.data["editable_fields"]), 0)

        # Common fields should be present
        self.assertIn("name", response.data["visible_fields"])
        self.assertIn("value", response.data["visible_fields"])

    def test_field_permissions_with_restricted_permission(self):
        """Test field permissions with custom restricted permission."""
        from statezero.adaptors.django.config import registry

        # Define a custom permission class with specific field restrictions
        class RestrictedPermission(AllowAllPermission):
            def visible_fields(self, request, model):
                return {"id", "name"}  # Only id and name visible

            def create_fields(self, request, model):
                return {"name"}  # Only name can be set on create

            def editable_fields(self, request, model):
                return {"name"}  # Only name can be edited

        # Override permissions temporarily
        original_config = registry.get_config(DummyModel)
        original_permissions = original_config._permissions
        original_config._permissions = [RestrictedPermission]

        try:
            url = reverse("statezero:field_permissions", args=["django_app.DummyModel"])

            response = self.client.get(url)

            self.assertEqual(response.status_code, 200)

            # Check visible fields
            self.assertIn("name", response.data["visible_fields"])
            self.assertIn("id", response.data["visible_fields"])
            self.assertNotIn("value", response.data["visible_fields"])

            # Check creatable fields
            self.assertIn("name", response.data["creatable_fields"])
            self.assertNotIn("value", response.data["creatable_fields"])

            # Check editable fields
            self.assertIn("name", response.data["editable_fields"])
            self.assertNotIn("value", response.data["editable_fields"])

        finally:
            # Restore original permissions
            original_config._permissions = original_permissions

    def test_field_permissions_model_not_found(self):
        """Test that requesting permissions for a non-existent model returns 404."""
        url = reverse("statezero:field_permissions", args=["nonexistent.Model"])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.data)

    def test_field_permissions_respects_frontend_fields(self):
        """Test that visible_fields respects the frontend_fields configuration."""
        from statezero.adaptors.django.config import registry

        original_config = registry.get_config(DummyModel)
        original_frontend_fields = original_config.frontend_fields

        # Restrict frontend_fields to only show id and name
        original_config.frontend_fields = {"id", "name"}

        try:
            url = reverse("statezero:field_permissions", args=["django_app.DummyModel"])

            response = self.client.get(url)

            self.assertEqual(response.status_code, 200)

            # visible_fields should be limited by frontend_fields
            self.assertIn("name", response.data["visible_fields"])
            self.assertIn("id", response.data["visible_fields"])
            # value should not be visible even with AllowAllPermission
            self.assertNotIn("value", response.data["visible_fields"])

            # creatable and editable should still include value (not limited by frontend_fields)
            self.assertIn("value", response.data["creatable_fields"])
            self.assertIn("value", response.data["editable_fields"])

        finally:
            # Restore original frontend_fields
            original_config.frontend_fields = original_frontend_fields

    def test_field_permissions_multiple_permissions_union(self):
        """Test that multiple permission classes result in a union of allowed fields."""
        from statezero.adaptors.django.config import registry

        class Permission1(AllowAllPermission):
            def visible_fields(self, request, model):
                return {"id", "name"}

        class Permission2(AllowAllPermission):
            def visible_fields(self, request, model):
                return {"id", "value"}

        original_config = registry.get_config(DummyModel)
        original_permissions = original_config._permissions
        original_config._permissions = [Permission1, Permission2]

        try:
            url = reverse("statezero:field_permissions", args=["django_app.DummyModel"])

            response = self.client.get(url)

            self.assertEqual(response.status_code, 200)

            # Should have union of both permissions: {id, name, value}
            self.assertIn("id", response.data["visible_fields"])
            self.assertIn("name", response.data["visible_fields"])
            self.assertIn("value", response.data["visible_fields"])

        finally:
            original_config._permissions = original_permissions
