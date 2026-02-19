"""Integration tests for AnyOf / AllOf action permissions via HTTP."""
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from statezero.core.actions import action_registry
from statezero.core.interfaces import AbstractActionPermission
from statezero.core.permissions import AnyOf, AllOf


# ---- Permission stubs ----

class IsAuthenticated(AbstractActionPermission):
    def has_permission(self, request, action_name: str) -> bool:
        return hasattr(request, "user") and request.user.is_authenticated

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        return True


class HasValidApiKey(AbstractActionPermission):
    def has_permission(self, request, action_name: str) -> bool:
        api_key = request.META.get("HTTP_X_API_KEY")
        return api_key == "test-key-456"

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        return True


class AlwaysDeny(AbstractActionPermission):
    def has_permission(self, request, action_name: str) -> bool:
        return False

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        return False


# ---- Helpers ----

def _register_test_action(name, permissions):
    """Register a trivial action that returns {"ok": True}."""

    def _action(*, request=None):
        return {"ok": True}

    action_registry.register(
        _action,
        name=name,
        permissions=permissions,
    )
    return name


class ActionPermissionIntegrationTest(APITestCase):
    """Test AnyOf/AllOf compositors through the real ActionView endpoint."""

    _registered_actions = []

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Register test actions once for the whole class
        cls._registered_actions = [
            _register_test_action(
                "test_allof_action",
                [AllOf(IsAuthenticated, HasValidApiKey)],
            ),
            _register_test_action(
                "test_anyof_action",
                [AnyOf(IsAuthenticated, HasValidApiKey)],
            ),
            _register_test_action(
                "test_nested_action",
                [AnyOf(AllOf(IsAuthenticated, HasValidApiKey), AlwaysDeny)],
            ),
            _register_test_action(
                "test_single_perm_legacy",
                [IsAuthenticated],
            ),
            _register_test_action(
                "test_list_perm_legacy",
                [IsAuthenticated, HasValidApiKey],
            ),
            _register_test_action(
                "test_anyof_instance_action",
                AnyOf(IsAuthenticated, HasValidApiKey),
            ),
        ]

    @classmethod
    def tearDownClass(cls):
        for name in cls._registered_actions:
            action_registry._actions.pop(name, None)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(username="permtest", password="password")

    # ---- AllOf tests ----

    def test_allof_denies_without_api_key(self):
        """AllOf(IsAuthenticated, HasValidApiKey) — authenticated but no API key."""
        self.client.login(username="permtest", password="password")
        url = reverse("statezero:action", args=["test_allof_action"])
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_allof_denies_unauthenticated_with_api_key(self):
        """AllOf(IsAuthenticated, HasValidApiKey) — API key but not authenticated."""
        url = reverse("statezero:action", args=["test_allof_action"])
        response = self.client.post(
            url, data={}, format="json", HTTP_X_API_KEY="test-key-456"
        )
        self.assertIn(response.status_code, [401, 403])

    def test_allof_passes_when_both_satisfied(self):
        """AllOf(IsAuthenticated, HasValidApiKey) — both satisfied."""
        self.client.login(username="permtest", password="password")
        url = reverse("statezero:action", args=["test_allof_action"])
        response = self.client.post(
            url, data={}, format="json", HTTP_X_API_KEY="test-key-456"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["ok"])

    # ---- AnyOf tests ----

    def test_anyof_passes_authenticated_no_key(self):
        """AnyOf(IsAuthenticated, HasValidApiKey) — authenticated is enough."""
        self.client.login(username="permtest", password="password")
        url = reverse("statezero:action", args=["test_anyof_action"])
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_anyof_passes_with_key_unauthenticated(self):
        """AnyOf(IsAuthenticated, HasValidApiKey) — API key alone is blocked by
        DRF view-level auth before reaching action permissions."""
        url = reverse("statezero:action", args=["test_anyof_action"])
        response = self.client.post(
            url, data={}, format="json", HTTP_X_API_KEY="test-key-456"
        )
        # DRF's global IsAuthenticated on ActionView rejects unauthenticated
        # requests before the action-level AnyOf check runs.
        self.assertIn(response.status_code, [401, 403])

    def test_anyof_denies_when_neither(self):
        """AnyOf(IsAuthenticated, HasValidApiKey) — neither satisfied."""
        url = reverse("statezero:action", args=["test_anyof_action"])
        response = self.client.post(url, data={}, format="json")
        self.assertIn(response.status_code, [401, 403])

    # ---- Nested tests ----

    def test_nested_passes_when_inner_allof_satisfied(self):
        """AnyOf(AllOf(IsAuthenticated, HasValidApiKey), AlwaysDeny) — inner AllOf passes."""
        self.client.login(username="permtest", password="password")
        url = reverse("statezero:action", args=["test_nested_action"])
        response = self.client.post(
            url, data={}, format="json", HTTP_X_API_KEY="test-key-456"
        )
        self.assertEqual(response.status_code, 200)

    def test_nested_denies_when_inner_allof_partial(self):
        """AnyOf(AllOf(IsAuthenticated, HasValidApiKey), AlwaysDeny) — only auth, no key."""
        self.client.login(username="permtest", password="password")
        url = reverse("statezero:action", args=["test_nested_action"])
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 403)

    # ---- Legacy (class-based) still works ----

    def test_single_permission_class_legacy(self):
        """Single permission class in list still works."""
        self.client.login(username="permtest", password="password")
        url = reverse("statezero:action", args=["test_single_perm_legacy"])
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_list_of_permission_classes_legacy(self):
        """List of permission classes (all must pass) still works."""
        self.client.login(username="permtest", password="password")
        url = reverse("statezero:action", args=["test_list_perm_legacy"])
        response = self.client.post(
            url, data={}, format="json", HTTP_X_API_KEY="test-key-456"
        )
        self.assertEqual(response.status_code, 200)

    def test_list_of_permission_classes_one_fails(self):
        """List of permission classes — one fails, denied."""
        self.client.login(username="permtest", password="password")
        url = reverse("statezero:action", args=["test_list_perm_legacy"])
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 403)

    # ---- AnyOf passed as single instance (not in a list) ----

    def test_anyof_as_single_permission_arg(self):
        """AnyOf instance passed directly (not in a list) works."""
        self.client.login(username="permtest", password="password")
        url = reverse("statezero:action", args=["test_anyof_instance_action"])
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 200)
