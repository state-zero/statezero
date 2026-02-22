"""
Tests for permission enforcement on aggregates, ordering, get_or_create,
and update_or_create.

Each test class targets a specific pathway where field-level or action-level
permissions must be enforced.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from statezero.client.runtime_template import (
    Model, configure, _field_permissions_cache,
    PermissionDenied, NotFound, ValidationError,
)
from statezero.client.testing import DjangoTestTransport
from tests.django_app.models import HFParent, ReadOnlyItem, UpdateOnlyItem

# Re-use client stubs from the existing security test module to avoid
# conflicting entries in the global _model_registry.
from tests.adaptors.django.test_client_security import (
    HFParentClient,
    ReadOnlyItemClient,
)

User = get_user_model()


# Only define stubs that don't already exist elsewhere.
class UpdateOnlyItemClient(Model):
    _model_name = "django_app.updateonlyitem"
    _pk_field = "id"
    _relations = {}


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class GapTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = User.objects.create_superuser(
            username="gap_admin", password="admin", email="gapadmin@test.com"
        )
        cls.user = User.objects.create_user(
            username="gap_user", password="user", email="gapuser@test.com"
        )

    def configure_as_admin(self):
        configure(transport=DjangoTestTransport(user=self.admin))
        _field_permissions_cache.clear()

    def configure_as_user(self):
        configure(transport=DjangoTestTransport(user=self.user))
        _field_permissions_cache.clear()


# ===========================================================================
# 1. Aggregates on hidden fields
# ===========================================================================

class TestAggregateOnHiddenField(GapTestBase):
    """
    HFParent hides the 'secret' field from non-admin users.
    Aggregate operations must not allow aggregating on hidden fields.
    """

    def setUp(self):
        super().setUp()
        HFParent.objects.create(name="a1", value=10, secret="alpha")
        HFParent.objects.create(name="a2", value=20, secret="beta")
        HFParent.objects.create(name="a3", value=30, secret="gamma")

    def test_admin_can_aggregate_on_any_field(self):
        """Admin can aggregate on all fields including secret."""
        self.configure_as_admin()
        result = HFParentClient.objects.sum("value")
        self.assertEqual(result, 60)

    def test_user_can_aggregate_on_visible_field(self):
        """Non-admin can aggregate on a visible field."""
        self.configure_as_user()
        result = HFParentClient.objects.sum("value")
        self.assertEqual(result, 60)

    def test_count_on_hidden_field_blocked(self):
        """Non-admin cannot COUNT a hidden field."""
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            HFParentClient.objects.all().count("secret")

    def test_min_on_hidden_field_blocked(self):
        """Non-admin cannot MIN a hidden field."""
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            HFParentClient.objects.min("secret")

    def test_max_on_hidden_field_blocked(self):
        """Non-admin cannot MAX a hidden field."""
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            HFParentClient.objects.max("secret")

    def test_count_star_allowed(self):
        """count('*') should always be allowed (no field reference)."""
        self.configure_as_user()
        result = HFParentClient.objects.count()
        self.assertEqual(result, 3)


# ===========================================================================
# 2. Ordering by hidden fields
# ===========================================================================

class TestOrderByHiddenField(GapTestBase):
    """
    Ordering by a hidden field leaks relative values through result order.
    The ordering must be restricted to visible fields.
    """

    def setUp(self):
        super().setUp()
        HFParent.objects.create(name="charlie", value=1, secret="aaa_first")
        HFParent.objects.create(name="alice", value=2, secret="zzz_last")
        HFParent.objects.create(name="bob", value=3, secret="mmm_middle")

    def test_admin_can_order_by_any_field(self):
        """Admin can order by secret."""
        self.configure_as_admin()
        results = HFParentClient.objects.order_by("secret").fetch()
        names = [r.name for r in results]
        self.assertEqual(names, ["charlie", "bob", "alice"])

    def test_user_can_order_by_visible_field(self):
        """Non-admin can order by a visible field."""
        self.configure_as_user()
        results = HFParentClient.objects.order_by("name").fetch()
        names = [r.name for r in results]
        self.assertEqual(names, ["alice", "bob", "charlie"])

    def test_order_by_hidden_field_blocked(self):
        """Non-admin cannot order by a hidden field."""
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            HFParentClient.objects.order_by("secret").fetch()

    def test_order_by_descending_hidden_field_blocked(self):
        """Non-admin cannot order by a hidden field (descending)."""
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            HFParentClient.objects.order_by("-secret").fetch()


# ===========================================================================
# 3. get_or_create bypasses CREATE permission
# ===========================================================================

class TestGetOrCreatePermissionEscalation(GapTestBase):
    """
    ReadOnlyItem: non-admin users only have READ permission.
    get_or_create must require CREATE permission when the object
    doesn't exist and would be created.
    """

    def test_user_cannot_create_directly(self):
        """Sanity: direct create is blocked for read-only users."""
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            ReadOnlyItemClient.objects.create(name="should_fail", value=1)

    def test_user_get_or_create_blocked(self):
        """Read-only user cannot use get_or_create (requires CREATE)."""
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            ReadOnlyItemClient.objects.get_or_create(
                name="new_via_goc",
                defaults={"value": 999},
            )

    def test_user_get_or_create_no_records_created(self):
        """Read-only user's get_or_create must not persist anything."""
        self.configure_as_user()
        try:
            ReadOnlyItemClient.objects.get_or_create(
                name="should_not_persist",
                defaults={"value": 123},
            )
        except PermissionDenied:
            pass
        self.assertFalse(
            ReadOnlyItem.objects.filter(name="should_not_persist").exists()
        )

    def test_admin_get_or_create_works(self):
        """Admin can still use get_or_create normally."""
        self.configure_as_admin()
        result, created = ReadOnlyItemClient.objects.get_or_create(
            name="admin_goc",
            defaults={"value": 42},
        )
        self.assertTrue(created)
        self.assertEqual(result.name, "admin_goc")


# ===========================================================================
# 4. update_or_create bypasses CREATE permission
# ===========================================================================

class TestUpdateOrCreatePermissionEscalation(GapTestBase):
    """
    UpdateOnlyItem: non-admin users have READ+UPDATE but NOT CREATE.
    update_or_create must require CREATE when the object doesn't exist.
    """

    def test_user_cannot_create_directly(self):
        """Sanity: direct create is blocked for update-only users."""
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            UpdateOnlyItemClient.objects.create(name="should_fail", value=1)

    def test_user_can_update_existing(self):
        """Update-only user can update existing records."""
        obj = UpdateOnlyItem.objects.create(name="updatable", value=10)
        self.configure_as_user()
        results = UpdateOnlyItemClient.objects.filter(id=obj.pk).update(name="updated")
        self.assertEqual(results[0].name, "updated")

    def test_update_or_create_blocked_even_if_exists(self):
        """update_or_create requires CREATE globally, even if record exists."""
        UpdateOnlyItem.objects.create(name="existing", value=10)
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            UpdateOnlyItemClient.objects.update_or_create(
                name="existing", defaults={"value": 99}
            )

    def test_update_or_create_blocked_when_new(self):
        """Update-only user cannot use update_or_create for new records."""
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            UpdateOnlyItemClient.objects.update_or_create(
                name="new_via_uoc",
                defaults={"value": 777},
            )

    def test_update_or_create_no_records_created(self):
        """Update-only user's update_or_create must not persist anything."""
        self.configure_as_user()
        try:
            UpdateOnlyItemClient.objects.update_or_create(
                name="should_not_persist",
                defaults={"value": 456},
            )
        except PermissionDenied:
            pass
        self.assertFalse(
            UpdateOnlyItem.objects.filter(name="should_not_persist").exists()
        )

    def test_admin_update_or_create_works(self):
        """Admin can still use update_or_create normally."""
        self.configure_as_admin()
        result, created = UpdateOnlyItemClient.objects.update_or_create(
            name="admin_uoc",
            defaults={"value": 42},
        )
        self.assertTrue(created)
        self.assertEqual(result.name, "admin_uoc")
