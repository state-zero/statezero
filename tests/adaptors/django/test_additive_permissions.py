"""
Test additive permissions with OR logic for filter_queryset
and AND logic for exclude_from_queryset.
"""
from typing import Any, Set, Type

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from statezero.core.interfaces import AbstractPermission
from statezero.core.types import ActionType, ORMModel, RequestType
from tests.django_app.models import DummyModel, DummyRelatedModel


class OwnerPermission(AbstractPermission):
    """Permission that only shows objects owned by the user."""

    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        # Only show objects where related.name matches the username
        return queryset.filter(related__name=request.user.username)

    def allowed_actions(self, request: RequestType, model: Type[ORMModel]) -> Set[ActionType]:
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE, ActionType.DELETE, ActionType.BULK_CREATE}

    def allowed_object_actions(self, request, obj, model: Type[ORMModel]) -> Set[ActionType]:
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE, ActionType.DELETE, ActionType.BULK_CREATE}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"


class PublicPermission(AbstractPermission):
    """Permission that shows public objects (value > 100)."""

    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        # Show objects with value > 100 (considered "public")
        return queryset.filter(value__gt=100)

    def allowed_actions(self, request: RequestType, model: Type[ORMModel]) -> Set[ActionType]:
        return {ActionType.READ}  # Public objects are read-only

    def allowed_object_actions(self, request, obj, model: Type[ORMModel]) -> Set[ActionType]:
        return {ActionType.READ}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return set()  # No editable fields for public objects

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return set()


class ExcludeArchivedPermission(AbstractPermission):
    """Permission that excludes archived objects (name starts with 'Archived')."""

    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        # Return none() to indicate this permission doesn't add any rows via OR logic
        # It only restricts via exclude_from_queryset
        return queryset.none()

    def exclude_from_queryset(self, request: RequestType, queryset: Any) -> Any:
        # Exclude archived objects
        return queryset.exclude(name__startswith="Archived")

    def allowed_actions(self, request: RequestType, model: Type[ORMModel]) -> Set[ActionType]:
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE, ActionType.DELETE, ActionType.BULK_CREATE}

    def allowed_object_actions(self, request, obj, model: Type[ORMModel]) -> Set[ActionType]:
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE, ActionType.DELETE, ActionType.BULK_CREATE}

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return "__all__"


class AdditivePermissionsTest(APITestCase):
    """Test that multiple permissions are combined with OR logic (additive)."""

    def setUp(self):
        # Create two users
        self.user1 = User.objects.create_user(username="user1", password="password")
        self.user2 = User.objects.create_user(username="user2", password="password")

        # Create related objects for ownership
        self.user1_related = DummyRelatedModel.objects.create(name="user1")
        self.user2_related = DummyRelatedModel.objects.create(name="user2")

        # Create test objects:
        # 1. Owned by user1, not public (value=50)
        self.user1_private = DummyModel.objects.create(
            name="User1Private",
            value=50,
            related=self.user1_related
        )

        # 2. Owned by user2, not public (value=75)
        self.user2_private = DummyModel.objects.create(
            name="User2Private",
            value=75,
            related=self.user2_related
        )

        # 3. Owned by user1, public (value=150)
        self.user1_public = DummyModel.objects.create(
            name="User1Public",
            value=150,
            related=self.user1_related
        )

        # 4. Owned by user2, public (value=200)
        self.user2_public = DummyModel.objects.create(
            name="User2Public",
            value=200,
            related=self.user2_related
        )

        # 5. Archived object owned by user1 (should be excluded)
        self.user1_archived = DummyModel.objects.create(
            name="ArchivedUser1Item",
            value=100,
            related=self.user1_related
        )

    def test_or_combination_of_permissions(self):
        """
        Test that filter_queryset from multiple permissions are combined with OR.

        With OwnerPermission and PublicPermission:
        - user1 should see: user1_private, user1_public, user2_public
          (owned by user1 OR public)
        - user2 should see: user2_private, user1_public, user2_public
          (owned by user2 OR public)
        """
        from statezero.adaptors.django.config import registry

        # Register model with both OwnerPermission and PublicPermission
        original_config = registry.get_config(DummyModel)
        original_permissions = original_config._permissions
        original_config._permissions = [OwnerPermission, PublicPermission]

        try:
            # Login as user1
            self.client.login(username="user1", password="password")

            url = reverse("statezero:model_view", args=["django_app.DummyModel"])
            payload = {
                "ast": {
                    "query": {
                        "type": "list",
                    }
                }
            }

            response = self.client.post(url, data=payload, format="json")
            self.assertEqual(response.status_code, 200, f"Failed: {response.data}")

            # user1 should see: user1_private (owned), user1_public (owned AND public),
            # user2_public (public), user1_archived (owned, not excluded yet)
            # Response structure: {"data": {"data": [ids...], "included": {...}}}
            result_data = response.data.get("data", {})
            ids = set(result_data.get("data", []))
            expected_ids = {self.user1_private.id, self.user1_public.id, self.user2_public.id, self.user1_archived.id}
            self.assertEqual(ids, expected_ids,
                           f"Expected {expected_ids} but got {ids}")

            # Now login as user2
            self.client.login(username="user2", password="password")

            response = self.client.post(url, data=payload, format="json")
            self.assertEqual(response.status_code, 200, f"Failed: {response.data}")

            # user2 should see: user2_private (owned), user1_public (public), user2_public (owned AND public)
            result_data = response.data.get("data", {})
            ids = set(result_data.get("data", []))
            expected_ids = {self.user2_private.id, self.user1_public.id, self.user2_public.id}
            self.assertEqual(ids, expected_ids,
                           f"Expected {expected_ids} but got {ids}")

        finally:
            # Restore original permissions
            original_config._permissions = original_permissions

    def test_exclude_from_queryset_and_logic(self):
        """
        Test that exclude_from_queryset is applied with AND logic (restrictive).

        With OwnerPermission, PublicPermission, and ExcludeArchivedPermission:
        - Rows visible if (owned OR public) AND not archived
        """
        from statezero.adaptors.django.config import registry

        # Register with all three permissions
        original_config = registry.get_config(DummyModel)
        original_permissions = original_config._permissions
        original_config._permissions = [OwnerPermission, PublicPermission, ExcludeArchivedPermission]

        try:
            # Login as user1
            self.client.login(username="user1", password="password")

            url = reverse("statezero:model_view", args=["django_app.DummyModel"])
            payload = {
                "ast": {
                    "query": {
                        "type": "list",
                    }
                }
            }

            response = self.client.post(url, data=payload, format="json")
            self.assertEqual(response.status_code, 200, f"Failed: {response.data}")

            # user1 should see: user1_private, user1_public, user2_public
            # BUT NOT user1_archived (excluded by ExcludeArchivedPermission)
            result_data = response.data.get("data", {})
            ids = set(result_data.get("data", []))
            expected_ids = {self.user1_private.id, self.user1_public.id, self.user2_public.id}
            self.assertEqual(ids, expected_ids,
                           f"Expected {expected_ids} but got {ids}. Archived item should be excluded!")

            # Verify user1_archived is NOT in the results
            self.assertNotIn(self.user1_archived.id, ids,
                           "Archived object should be excluded!")

        finally:
            # Restore original permissions
            original_config._permissions = original_permissions
