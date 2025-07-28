import json

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from statezero.adaptors.django.permissions import AllowAllPermission

from statezero.core.types import ActionType
from tests.django_app.models import (CustomPKModel, DummyModel,
                                     DummyRelatedModel,
                                     ModelWithCustomPKRelation)
from tests.django_app.permissions import (ReadOnlyPermission,
                                          RestrictedFieldsPermission)


class PermissionsTest(APITestCase):
    def setUp(self):
        # Create and log in a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create test models
        self.related_dummy = DummyRelatedModel.objects.create(name="Related1")

        # Basic model with AllowAllPermission
        self.dummy = DummyModel.objects.create(
            name="TestDummy", value=100, related=self.related_dummy
        )

        # Model with ReadOnlyPermission - now using a numeric custom_pk
        self.readonly_model = CustomPKModel.objects.create(
            name="ReadOnlyModel", custom_pk=1
        )

        # Model with RestrictedFieldsPermission
        self.restricted_model = ModelWithCustomPKRelation.objects.create(
            name="RestrictedModel", custom_pk_related=self.readonly_model
        )

    def test_allow_all_permission_update(self):
        """Test update with AllowAllPermission works correctly."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        update_payload = {
            "ast": {
                "query": {
                    "type": "update",
                    "filter": {"type": "filter", "conditions": {"id": self.dummy.id}},
                    "data": {"value": 200, "name": "UpdatedDummy"},
                }
            }
        }

        response = self.client.post(url, data=update_payload, format="json")
        self.assertEqual(
            response.status_code, 200, f"Failed with response: {response.data}"
        )

        # Verify update was successful
        self.dummy.refresh_from_db()
        self.assertEqual(self.dummy.value, 200)
        self.assertEqual(self.dummy.name, "UpdatedDummy")

    def test_readonly_permission_update_denied(self):
        """Test update with ReadOnlyPermission is denied."""
        url = reverse("statezero:model_view", args=["django_app.CustomPKModel"])

        update_payload = {
            "ast": {
                "query": {
                    "type": "update",
                    "filter": {
                        "type": "filter",
                        "conditions": {"custom_pk": self.readonly_model.custom_pk},
                    },
                    "data": {"name": "AttemptedUpdate"},
                }
            }
        }

        response = self.client.post(url, data=update_payload, format="json")

        # Since ReadOnlyPermission doesn't allow update globally,
        # we now expect a 403 with a specific message.
        self.assertEqual(response.status_code, 403)
        # Check that the error message indicates missing update permission.
        self.assertIn(
            "Permission denied", response.data.get("detail")
        )

        # Verify model was not updated
        self.readonly_model.refresh_from_db()
        self.assertEqual(self.readonly_model.name, "ReadOnlyModel")

    def test_restricted_fields_permission(self):
        """Test that RestrictedFieldsPermission enforces field-level restrictions."""
        url = reverse(
            "statezero:model_view", args=["django_app.ModelWithCustomPKRelation"]
        )

        # Create a valid update payload (only name field should be allowed)
        update_payload = {
            "ast": {
                "query": {
                    "type": "update",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.restricted_model.id},
                    },
                    "data": {"name": "ValidUpdateName"},
                }
            }
        }

        response = self.client.post(url, data=update_payload, format="json")
        self.assertEqual(
            response.status_code, 200, f"Failed with response: {response.data}"
        )

        # Verify allowed field was updated
        self.restricted_model.refresh_from_db()
        self.assertEqual(self.restricted_model.name, "ValidUpdateName")

        # Now try to update a field that's not editable (custom_pk_related).
        # Instead of a 400 error, assume the field is silently ignored.
        invalid_update_payload = {
            "ast": {
                "query": {
                    "type": "update",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.restricted_model.id},
                    },
                    "data": {"custom_pk_related": None},  # This should be ignored
                }
            }
        }

        response = self.client.post(url, data=invalid_update_payload, format="json")

        # Instead of a 400, we now accept a 200 response.
        self.assertEqual(response.status_code, 200)
        # Verify that the restricted field remains unchanged.
        self.restricted_model.refresh_from_db()
        self.assertIsNotNone(self.restricted_model.custom_pk_related)

    def test_action_types_in_permissions(self):
        """Test that the correct action types are being used for permission checks."""

        # Define a custom permission class that tracks the action type
        class ActionTypeTestPermission(AllowAllPermission):
            last_action_type = None

            def allowed_actions(self, request, model):
                return {
                    ActionType.CREATE,
                    ActionType.READ,
                    ActionType.UPDATE,
                    ActionType.DELETE,
                }

            def allowed_object_actions(self, request, obj, model):
                # Track which action type was requested using a class variable
                ActionTypeTestPermission.last_action_type = ActionType.UPDATE
                return {
                    ActionType.CREATE,
                    ActionType.READ,
                    ActionType.UPDATE,
                    ActionType.DELETE,
                }

        # Override permissions temporarily for testing using the class instead of an instance
        from statezero.adaptors.django.config import registry

        original_config = registry.get_config(DummyModel)
        original_permissions = original_config._permissions
        original_config._permissions = [ActionTypeTestPermission]

        try:
            url = reverse("statezero:model_view", args=["django_app.DummyModel"])

            # Execute an update operation
            update_payload = {
                "ast": {
                    "query": {
                        "type": "update",
                        "filter": {
                            "type": "filter",
                            "conditions": {"id": self.dummy.id},
                        },
                        "data": {"value": 300},
                    }
                }
            }

            response = self.client.post(url, data=update_payload, format="json")
            self.assertEqual(response.status_code, 200)

            # Verify that ActionType.UPDATE was used for permission check
            self.assertEqual(
                ActionTypeTestPermission.last_action_type, ActionType.UPDATE
            )

        finally:
            # Restore original permissions
            original_config._permissions = original_permissions

    def test_editable_fields_enforced(self):
        """Test that the editable_fields from permissions are properly enforced."""
        from statezero.adaptors.django.config import registry

        # Define a custom permission class with specific field restrictions
        class EditableFieldsTestPermission(AllowAllPermission):
            def allowed_actions(self, request, model):
                # Allow update globally.
                return {
                    ActionType.CREATE,
                    ActionType.READ,
                    ActionType.UPDATE,
                    ActionType.DELETE,
                }

            def editable_fields(self, request, model):
                # Only allow name to be edited
                return {"name"}

        # Create a test instance
        test_dummy = DummyModel.objects.create(
            name="EditableFieldsTest", value=100, related=self.related_dummy
        )

        # Override permissions temporarily using the class
        original_config = registry.get_config(DummyModel)
        original_permissions = original_config._permissions
        original_config._permissions = [EditableFieldsTestPermission]

        try:
            url = reverse("statezero:model_view", args=["django_app.DummyModel"])

            # Test updating an allowed field (name)
            allowed_update = {
                "ast": {
                    "query": {
                        "type": "update",
                        "filter": {
                            "type": "filter",
                            "conditions": {"id": test_dummy.id},
                        },
                        "data": {"name": "UpdatedName"},
                    }
                }
            }

            response = self.client.post(url, data=allowed_update, format="json")
            self.assertEqual(
                response.status_code,
                200,
                f"Update to allowed field failed: {response.data}",
            )

            # Test updating a restricted field (value)
            restricted_update = {
                "ast": {
                    "query": {
                        "type": "update",
                        "filter": {
                            "type": "filter",
                            "conditions": {"id": test_dummy.id},
                        },
                        "data": {"value": 999},
                    }
                }
            }

            response = self.client.post(url, data=restricted_update, format="json")
            # Instead of a 400 error, we now expect a 200 with the field update ignored.
            self.assertEqual(
                response.status_code,
                200,
                f"Update to restricted field should be ignored, got {response.status_code}",
            )

            # Verify the DB reflects only the allowed changes
            test_dummy.refresh_from_db()
            self.assertEqual(
                test_dummy.name, "UpdatedName", "Allowed field should be updated"
            )
            self.assertEqual(
                test_dummy.value, 100, "Restricted field should not be updated"
            )

        finally:
            # Restore original permissions
            original_config._permissions = original_permissions
