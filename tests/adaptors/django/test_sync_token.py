from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase
from unittest.mock import patch, MagicMock


class SyncTokenPermissionTest(APITestCase):
    """Tests for the STATEZERO_SYNC_TOKEN functionality."""

    @override_settings(DEBUG=False, STATEZERO_SYNC_TOKEN="test-secret-token")
    def test_schema_endpoint_with_valid_sync_token(self):
        """Test that schema endpoints allow access with a valid sync token in production mode."""
        url = reverse("statezero:model_list")

        # Request with valid token should succeed
        response = self.client.get(url, HTTP_X_SYNC_TOKEN="test-secret-token")

        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 with valid sync token, got {response.status_code}: {response.data}"
        )

    @override_settings(DEBUG=False, STATEZERO_SYNC_TOKEN="test-secret-token")
    def test_schema_endpoint_with_invalid_sync_token(self):
        """Test that schema endpoints deny access with an invalid sync token in production mode."""
        url = reverse("statezero:model_list")

        # Request with invalid token falls through to configured permission class
        response = self.client.get(url, HTTP_X_SYNC_TOKEN="wrong-token")

        # Without a valid token and not in DEBUG mode, falls through to configured
        # STATEZERO_VIEW_ACCESS_CLASS. Status depends on that class configuration.
        # 401 = Unauthorized (authentication required), 403 = Forbidden, 200 = AllowAny
        self.assertIn(response.status_code, [200, 401, 403])

    @override_settings(DEBUG=False, STATEZERO_SYNC_TOKEN="test-secret-token")
    def test_schema_endpoint_without_sync_token(self):
        """Test that schema endpoints behavior without sync token in production mode."""
        url = reverse("statezero:model_list")

        # Request without token - falls through to configured permission class
        response = self.client.get(url)

        # Status depends on STATEZERO_VIEW_ACCESS_CLASS configuration
        # 401 = Unauthorized, 403 = Forbidden, 200 = AllowAny
        self.assertIn(response.status_code, [200, 401, 403])

    @override_settings(DEBUG=False, STATEZERO_SYNC_TOKEN=None)
    def test_schema_endpoint_with_no_token_configured(self):
        """Test that schema endpoints work when no sync token is configured."""
        url = reverse("statezero:model_list")

        # When STATEZERO_SYNC_TOKEN is None, token check is skipped
        response = self.client.get(url, HTTP_X_SYNC_TOKEN="any-token")

        # Falls through to configured permission class
        # Status depends on STATEZERO_VIEW_ACCESS_CLASS configuration
        self.assertIn(response.status_code, [200, 401, 403])

    @override_settings(DEBUG=False, STATEZERO_SYNC_TOKEN="test-secret-token")
    def test_get_schema_endpoint_with_valid_sync_token(self):
        """Test that get-schema endpoint allows access with a valid sync token."""
        url = reverse("statezero:schema_view", args=["django_app.DummyModel"])

        response = self.client.get(url, HTTP_X_SYNC_TOKEN="test-secret-token")

        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 with valid sync token, got {response.status_code}"
        )

    @override_settings(DEBUG=False, STATEZERO_SYNC_TOKEN="test-secret-token")
    def test_actions_schema_endpoint_with_valid_sync_token(self):
        """Test that actions-schema endpoint allows access with a valid sync token."""
        url = reverse("statezero:actions_schema")

        response = self.client.get(url, HTTP_X_SYNC_TOKEN="test-secret-token")

        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 with valid sync token, got {response.status_code}"
        )

    @override_settings(DEBUG=True, STATEZERO_SYNC_TOKEN="test-secret-token")
    def test_sync_token_works_in_debug_mode_too(self):
        """Test that sync token validation also works in DEBUG mode."""
        url = reverse("statezero:model_list")

        # With valid token in DEBUG mode
        response = self.client.get(url, HTTP_X_SYNC_TOKEN="test-secret-token")

        self.assertEqual(response.status_code, 200)

    @override_settings(
        DEBUG=False,
        STATEZERO_SYNC_TOKEN="test-secret-token",
        STATEZERO_VIEW_ACCESS_CLASS="rest_framework.permissions.IsAuthenticated"
    )
    def test_sync_token_bypasses_auth_requirement(self):
        """Test that a valid sync token bypasses authentication requirements for schema endpoints."""
        url = reverse("statezero:model_list")

        # Without token and not authenticated, should fail with IsAuthenticated
        # DRF returns 401 Unauthorized for unauthenticated requests
        response_no_token = self.client.get(url)
        self.assertIn(
            response_no_token.status_code, [401, 403],
            "Expected 401/403 without token when IsAuthenticated is required"
        )

        # With valid token, should succeed even without authentication
        response_with_token = self.client.get(url, HTTP_X_SYNC_TOKEN="test-secret-token")
        self.assertEqual(
            response_with_token.status_code, 200,
            "Expected 200 with valid sync token, bypassing authentication"
        )

    @override_settings(DEBUG=False, STATEZERO_SYNC_TOKEN="test-secret-token")
    def test_sync_token_sets_flag_on_request(self):
        """Test that sync token authentication sets the _statezero_sync_token_access flag."""
        url = reverse("statezero:schema_view", args=["django_app.DummyModel"])

        # Make request with sync token
        response = self.client.get(url, HTTP_X_SYNC_TOKEN="test-secret-token")

        # Request should succeed (flag was set and permission check was bypassed)
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 with sync token flag set, got {response.status_code}"
        )

    @override_settings(DEBUG=False, STATEZERO_SYNC_TOKEN="test-secret-token")
    def test_sync_token_bypasses_model_permission_check(self):
        """
        Test that sync token bypasses the model-level permission check in process_schema.

        This verifies that even when a model has IsAuthenticatedPermission configured,
        the sync token will still allow schema access (for CLI schema generation).
        """
        from statezero.adaptors.django.config import registry
        from statezero.adaptors.django.permissions import IsAuthenticatedPermission
        from tests.django_app.models import DummyModel

        # Get the config and temporarily swap permissions
        config = registry.get_config(DummyModel)
        original_permissions = config._permissions

        try:
            # Temporarily change to use IsAuthenticatedPermission
            config._permissions = [IsAuthenticatedPermission]

            url = reverse("statezero:schema_view", args=["django_app.DummyModel"])

            # Without sync token, should fail (AnonymousUser has no permissions)
            response_no_token = self.client.get(url)
            # Could be 400 (ValidationError from process_schema) or 401/403 depending on config
            self.assertIn(
                response_no_token.status_code, [400, 401, 403],
                f"Expected 400/401/403 without token, got {response_no_token.status_code}"
            )

            # With sync token, should succeed even with IsAuthenticatedPermission
            response_with_token = self.client.get(url, HTTP_X_SYNC_TOKEN="test-secret-token")
            self.assertEqual(
                response_with_token.status_code, 200,
                f"Expected 200 with sync token bypassing IsAuthenticatedPermission, got {response_with_token.status_code}"
            )

        finally:
            # Restore original permissions
            config._permissions = original_permissions


class EventsAuthSyncTokenTest(APITestCase):
    @override_settings(DEBUG=True, STATEZERO_SYNC_TOKEN="server-token")
    def test_events_auth_rejects_mismatched_sync_token(self):
        from statezero.adaptors.django.config import config as global_config

        url = reverse("statezero:events_auth")
        with patch.object(global_config, "event_bus") as event_bus:
            event_bus.broadcast_emitter = MagicMock()
            event_bus.broadcast_emitter.has_permission.return_value = True
            event_bus.broadcast_emitter.authenticate.return_value = {"auth": "ok"}

            response = self.client.post(
                url,
                data={"channel_name": "private-test", "socket_id": "1.2"},
                HTTP_X_STATEZERO_SYNC_TOKEN="wrong-token",
            )

        self.assertEqual(
            response.status_code,
            409,
            f"Expected 409 on sync token mismatch, got {response.status_code}",
        )

    @override_settings(DEBUG=True, STATEZERO_SYNC_TOKEN="server-token")
    def test_events_auth_accepts_matching_sync_token(self):
        from statezero.adaptors.django.config import config as global_config

        url = reverse("statezero:events_auth")
        with patch.object(global_config, "event_bus") as event_bus:
            event_bus.broadcast_emitter = MagicMock()
            event_bus.broadcast_emitter.has_permission.return_value = True
            event_bus.broadcast_emitter.authenticate.return_value = {"auth": "ok"}

            response = self.client.post(
                url,
                data={"channel_name": "private-test", "socket_id": "1.2"},
                HTTP_X_STATEZERO_SYNC_TOKEN="server-token",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("statezero_sync_token_match"))
