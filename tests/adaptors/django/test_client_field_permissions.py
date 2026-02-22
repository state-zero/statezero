"""
Field permissions and deep filtering tests through the Python client.

Migrated from test_field_permissions_view.py and test_filtering_integration.py.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from statezero.client.runtime_template import (
    Model, configure, _field_permissions_cache, NotFound,
)
from statezero.client.testing import DjangoTestTransport
from statezero.adaptors.django.config import registry
from statezero.adaptors.django.permissions import AllowAllPermission
from tests.django_app.models import (
    DummyModel, DummyRelatedModel,
    DeepModelLevel1, DeepModelLevel2, DeepModelLevel3,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Client model stubs
# ---------------------------------------------------------------------------

class DummyModelClient(Model):
    _model_name = "django_app.dummymodel"
    _pk_field = "id"
    _relations = {"related": "django_app.dummyrelatedmodel"}


class DeepModelLevel1Client(Model):
    _model_name = "django_app.deepmodellevel1"
    _pk_field = "id"
    _relations = {"level2": "django_app.deepmodellevel2"}


class DeepModelLevel2Client(Model):
    _model_name = "django_app.deepmodellevel2"
    _pk_field = "id"
    _relations = {"level3": "django_app.deepmodellevel3"}


class DeepModelLevel3Client(Model):
    _model_name = "django_app.deepmodellevel3"
    _pk_field = "id"
    _relations = {}


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class FieldPermTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = User.objects.create_user(
            username="fp_user", password="password", email="fp@test.com"
        )

    def setUp(self):
        self.transport = DjangoTestTransport(user=self.user)
        configure(transport=self.transport)
        _field_permissions_cache.clear()


# ===========================================================================
# Field permissions via transport.get_field_permissions()
# ===========================================================================

class TestFieldPermissions(FieldPermTestBase):

    def test_allow_all_returns_all_field_types(self):
        """AllowAllPermission returns visible, creatable, and editable fields."""
        data = self.transport.get_field_permissions("django_app.DummyModel")
        self.assertIn("visible_fields", data)
        self.assertIn("creatable_fields", data)
        self.assertIn("editable_fields", data)
        self.assertIsInstance(data["visible_fields"], list)
        self.assertIn("name", data["visible_fields"])
        self.assertIn("value", data["visible_fields"])

    def test_restricted_permission(self):
        """Custom restricted permission limits returned fields."""
        class RestrictedPermission(AllowAllPermission):
            def visible_fields(self, request, model):
                return {"id", "name"}
            def create_fields(self, request, model):
                return {"name"}
            def editable_fields(self, request, model):
                return {"name"}

        config = registry.get_config(DummyModel)
        original = config._permissions
        config._permissions = [RestrictedPermission]
        try:
            data = self.transport.get_field_permissions("django_app.DummyModel")
            self.assertIn("name", data["visible_fields"])
            self.assertIn("id", data["visible_fields"])
            self.assertNotIn("value", data["visible_fields"])
            self.assertIn("name", data["creatable_fields"])
            self.assertNotIn("value", data["creatable_fields"])
            self.assertIn("name", data["editable_fields"])
            self.assertNotIn("value", data["editable_fields"])
        finally:
            config._permissions = original

    def test_unknown_model_raises(self):
        """Non-existent model returns 404 via the transport."""
        from statezero.client.runtime_template import StateZeroError
        with self.assertRaises(StateZeroError):
            self.transport.get_field_permissions("nonexistent.Model")

    def test_permission_union(self):
        """Multiple permission classes → union of visible fields."""
        class Perm1(AllowAllPermission):
            def visible_fields(self, request, model):
                return {"id", "name"}

        class Perm2(AllowAllPermission):
            def visible_fields(self, request, model):
                return {"id", "value"}

        config = registry.get_config(DummyModel)
        original = config._permissions
        config._permissions = [Perm1, Perm2]
        try:
            data = self.transport.get_field_permissions("django_app.DummyModel")
            visible = set(data["visible_fields"])
            self.assertIn("id", visible)
            self.assertIn("name", visible)
            self.assertIn("value", visible)
        finally:
            config._permissions = original


# ===========================================================================
# Deep nested filtering (3-level FK chain)
# ===========================================================================

class TestDeepNestedFiltering(FieldPermTestBase):

    def setUp(self):
        super().setUp()
        self.deep3 = DeepModelLevel3.objects.create(name="Deep3")
        self.deep2 = DeepModelLevel2.objects.create(name="Level2", level3=self.deep3)
        self.deep1 = DeepModelLevel1.objects.create(name="Level1", level2=self.deep2)

    def test_filter_three_levels_deep(self):
        """Filter DeepModelLevel1 by level2__level3__name."""
        results = DeepModelLevel1Client.objects.filter(
            level2__level3__name="Deep3"
        ).fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Level1")

    def test_filter_three_levels_deep_no_match(self):
        """No match when the deepest name doesn't exist."""
        results = DeepModelLevel1Client.objects.filter(
            level2__level3__name="Nonexistent"
        ).fetch()
        self.assertEqual(len(results), 0)

    def test_filter_three_levels_deep_with_depth(self):
        """Fetch with depth=2 resolves nested relations."""
        results = DeepModelLevel1Client.objects.filter(
            level2__level3__name="Deep3"
        ).fetch(depth=2)
        self.assertEqual(len(results), 1)
        resolved_level2 = results[0].level2
        self.assertIsInstance(resolved_level2, DeepModelLevel2Client)
        resolved_level3 = resolved_level2.level3
        self.assertIsInstance(resolved_level3, DeepModelLevel3Client)
        self.assertEqual(resolved_level3.name, "Deep3")
