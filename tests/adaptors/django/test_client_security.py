"""
Security tests: permission enforcement through the Python client.

Each test class uses its own model with a dedicated permission class.
Tests verify that non-superusers are properly restricted.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from statezero.client.runtime_template import (
    Model, configure, _field_permissions_cache,
    PermissionDenied, NotFound, MultipleObjectsReturned, ValidationError,
)
from statezero.client.testing import DjangoTestTransport
from tests.django_app.models import (
    ReadOnlyItem, NoDeleteItem, HFParent, HFChild,
    RowFilteredItem, RestrictedCreateItem, RestrictedEditItem,
    ExcludedItem, ObjectLevelItem, ComposedItem,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Client model stubs
# ---------------------------------------------------------------------------

class ReadOnlyItemClient(Model):
    _model_name = "django_app.readonlyitem"
    _pk_field = "id"
    _relations = {}


class NoDeleteItemClient(Model):
    _model_name = "django_app.nodeleteitem"
    _pk_field = "id"
    _relations = {}


class HFParentClient(Model):
    _model_name = "django_app.hfparent"
    _pk_field = "id"
    _relations = {}


class HFChildClient(Model):
    _model_name = "django_app.hfchild"
    _pk_field = "id"
    _relations = {"parent": "django_app.hfparent"}


class RowFilteredItemClient(Model):
    _model_name = "django_app.rowfiltereditem"
    _pk_field = "id"
    _relations = {}


class RestrictedCreateItemClient(Model):
    _model_name = "django_app.restrictedcreateitem"
    _pk_field = "id"
    _relations = {}


class RestrictedEditItemClient(Model):
    _model_name = "django_app.restrictededititem"
    _pk_field = "id"
    _relations = {}


class ExcludedItemClient(Model):
    _model_name = "django_app.excludeditem"
    _pk_field = "id"
    _relations = {}


class ObjectLevelItemClient(Model):
    _model_name = "django_app.objectlevelitem"
    _pk_field = "id"
    _relations = {}


class ComposedItemClient(Model):
    _model_name = "django_app.composeditem"
    _pk_field = "id"
    _relations = {}


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class SecurityTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = User.objects.create_superuser(
            username="sec_admin", password="admin", email="secadmin@test.com"
        )
        cls.user = User.objects.create_user(
            username="sec_user", password="user", email="secuser@test.com"
        )

    def configure_as_admin(self):
        configure(transport=DjangoTestTransport(user=self.admin))
        _field_permissions_cache.clear()

    def configure_as_user(self):
        configure(transport=DjangoTestTransport(user=self.user))
        _field_permissions_cache.clear()


# ===========================================================================
# ReadOnly
# ===========================================================================

class TestReadOnlyPermissions(SecurityTestBase):

    def test_can_read(self):
        ReadOnlyItem.objects.create(name="ro_item", value=10, secret="s")
        self.configure_as_user()
        results = ReadOnlyItemClient.objects.all().fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "ro_item")

    def test_cannot_create(self):
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            ReadOnlyItemClient.objects.create(name="fail", value=1)

    def test_cannot_update(self):
        obj = ReadOnlyItem.objects.create(name="ro_upd", value=10)
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            ReadOnlyItemClient.objects.filter(id=obj.pk).update(name="changed")

    def test_cannot_delete(self):
        obj = ReadOnlyItem.objects.create(name="ro_del", value=10)
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            ReadOnlyItemClient.objects.filter(id=obj.pk).delete()

    def test_admin_can_write(self):
        self.configure_as_admin()
        result = ReadOnlyItemClient.objects.create(name="admin_write", value=99)
        self.assertIsNotNone(result.pk)
        self.assertEqual(result.name, "admin_write")


# ===========================================================================
# NoDelete
# ===========================================================================

class TestNoDeletePermissions(SecurityTestBase):

    def test_can_create(self):
        self.configure_as_user()
        result = NoDeleteItemClient.objects.create(name="nd_item", value=10)
        self.assertIsNotNone(result.pk)

    def test_can_read(self):
        NoDeleteItem.objects.create(name="nd_read", value=5)
        self.configure_as_user()
        results = NoDeleteItemClient.objects.all().fetch()
        self.assertGreaterEqual(len(results), 1)

    def test_can_update(self):
        obj = NoDeleteItem.objects.create(name="nd_upd", value=10)
        self.configure_as_user()
        results = NoDeleteItemClient.objects.filter(id=obj.pk).update(name="updated")
        self.assertEqual(results[0].name, "updated")

    def test_cannot_delete(self):
        obj = NoDeleteItem.objects.create(name="nd_del", value=10)
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            NoDeleteItemClient.objects.filter(id=obj.pk).delete()

    def test_admin_can_delete(self):
        obj = NoDeleteItem.objects.create(name="nd_admin_del", value=10)
        self.configure_as_admin()
        count = NoDeleteItemClient.objects.filter(id=obj.pk).delete()
        self.assertEqual(count, 1)


# ===========================================================================
# HiddenFields
# ===========================================================================

class TestHiddenFieldPermissions(SecurityTestBase):

    def test_secret_not_in_response(self):
        HFParent.objects.create(name="hf_test", value=10, secret="top_secret")
        self.configure_as_user()
        results = HFParentClient.objects.all().fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "hf_test")
        # secret should not be present
        self.assertNotIn("secret", results[0].to_dict())

    def test_admin_sees_secret(self):
        HFParent.objects.create(name="hf_admin", value=10, secret="visible_secret")
        self.configure_as_admin()
        results = HFParentClient.objects.all().fetch()
        self.assertEqual(len(results), 1)
        self.assertIn("secret", results[0].to_dict())
        self.assertEqual(results[0].secret, "visible_secret")

    def test_hidden_at_depth(self):
        """Fetch HFChild at depth=1, parent's secret should be hidden."""
        parent = HFParent.objects.create(name="hf_depth", value=10, secret="deep_secret")
        HFChild.objects.create(name="child", parent=parent)
        self.configure_as_user()
        results = HFChildClient.objects.all().fetch(depth=1)
        self.assertEqual(len(results), 1)
        resolved_parent = results[0].parent
        self.assertIsInstance(resolved_parent, HFParentClient)
        self.assertEqual(resolved_parent.name, "hf_depth")
        self.assertNotIn("secret", resolved_parent.to_dict())


# ===========================================================================
# RowFiltered
# ===========================================================================

class TestRowFilteredPermissions(SecurityTestBase):

    def setUp(self):
        super().setUp()
        RowFilteredItem.objects.create(name="visible_item1", value=10)
        RowFilteredItem.objects.create(name="visible_item2", value=20)
        RowFilteredItem.objects.create(name="hidden_item", value=30)

    def test_only_visible_rows(self):
        self.configure_as_user()
        results = RowFilteredItemClient.objects.all().fetch()
        names = {r.name for r in results}
        self.assertEqual(names, {"visible_item1", "visible_item2"})

    def test_admin_sees_all(self):
        self.configure_as_admin()
        results = RowFilteredItemClient.objects.all().fetch()
        self.assertEqual(len(results), 3)

    def test_count_respects_filter(self):
        self.configure_as_user()
        count = RowFilteredItemClient.objects.count()
        self.assertEqual(count, 2)

    def test_get_invisible_raises_not_found(self):
        """Trying to get a filtered-out row by id should raise NotFound.

        BUG: client get(id=X) sends conditions as a separate key in the AST,
        but the server-side engine.get() only looks at node["filter"] and
        ignores node["conditions"]. So the conditions are never applied and
        the get() operates on the entire permission-filtered queryset, which
        returns 2 visible rows → MultipleObjectsReturned instead of NotFound.
        """
        hidden = RowFilteredItem.objects.get(name="hidden_item")
        self.configure_as_user()
        with self.assertRaises(NotFound):
            RowFilteredItemClient.objects.get(id=hidden.pk)


# ===========================================================================
# RestrictedCreate
# ===========================================================================

class TestRestrictedCreatePermissions(SecurityTestBase):

    def test_create_with_allowed_field(self):
        self.configure_as_user()
        result = RestrictedCreateItemClient.objects.create(name="rc_item")
        self.assertIsNotNone(result.pk)
        self.assertEqual(result.name, "rc_item")

    def test_create_extra_fields_dropped(self):
        """value and secret should be silently dropped for non-admin."""
        self.configure_as_user()
        result = RestrictedCreateItemClient.objects.create(
            name="rc_dropped", value=999, secret="should_drop"
        )
        self.assertIsNotNone(result.pk)
        self.assertEqual(result.name, "rc_dropped")
        obj = RestrictedCreateItem.objects.get(pk=result.pk)
        # value should be default (0), secret should be default ("")
        self.assertEqual(obj.value, 0)
        self.assertEqual(obj.secret, "")

    def test_admin_can_set_all_fields(self):
        self.configure_as_admin()
        result = RestrictedCreateItemClient.objects.create(
            name="rc_admin", value=999, secret="full_access"
        )
        obj = RestrictedCreateItem.objects.get(pk=result.pk)
        self.assertEqual(obj.value, 999)
        self.assertEqual(obj.secret, "full_access")


# ===========================================================================
# RestrictedEdit
# ===========================================================================

class TestRestrictedEditPermissions(SecurityTestBase):

    def test_update_allowed_field(self):
        obj = RestrictedEditItem.objects.create(name="re_upd", value=10, secret="s")
        self.configure_as_user()
        results = RestrictedEditItemClient.objects.filter(id=obj.pk).update(name="re_changed")
        self.assertEqual(results[0].name, "re_changed")

    def test_update_restricted_field_dropped(self):
        """value update should be silently dropped for non-admin."""
        obj = RestrictedEditItem.objects.create(name="re_drop", value=10, secret="s")
        self.configure_as_user()
        RestrictedEditItemClient.objects.filter(id=obj.pk).update(
            name="re_updated", value=999
        )
        obj.refresh_from_db()
        self.assertEqual(obj.name, "re_updated")
        self.assertEqual(obj.value, 10)  # value unchanged

    def test_admin_can_update_all(self):
        obj = RestrictedEditItem.objects.create(name="re_admin", value=10, secret="s")
        self.configure_as_admin()
        RestrictedEditItemClient.objects.filter(id=obj.pk).update(
            name="re_admin_upd", value=999
        )
        obj.refresh_from_db()
        self.assertEqual(obj.name, "re_admin_upd")
        self.assertEqual(obj.value, 999)


# ===========================================================================
# ExcludeFromQueryset
# ===========================================================================

class TestExcludeFromQuerysetPermissions(SecurityTestBase):

    def setUp(self):
        super().setUp()
        ExcludedItem.objects.create(name="archived_item", value=10)
        ExcludedItem.objects.create(name="active_item", value=20)

    def test_archived_excluded(self):
        self.configure_as_user()
        results = ExcludedItemClient.objects.all().fetch()
        names = {r.name for r in results}
        self.assertNotIn("archived_item", names)

    def test_non_archived_visible(self):
        self.configure_as_user()
        results = ExcludedItemClient.objects.all().fetch()
        names = {r.name for r in results}
        self.assertIn("active_item", names)

    def test_admin_also_excluded(self):
        """exclude_from_queryset applies to ALL users including admin."""
        self.configure_as_admin()
        results = ExcludedItemClient.objects.all().fetch()
        names = {r.name for r in results}
        self.assertNotIn("archived_item", names)
        self.assertIn("active_item", names)


# ===========================================================================
# ObjectLevel
# ===========================================================================

class TestObjectLevelPermissions(SecurityTestBase):

    def setUp(self):
        super().setUp()
        self.own_item = ObjectLevelItem.objects.create(
            name="my_item", value=10, owner="sec_user"
        )
        self.other_item = ObjectLevelItem.objects.create(
            name="their_item", value=20, owner="someone_else"
        )

    def test_can_update_own(self):
        self.configure_as_user()
        results = ObjectLevelItemClient.objects.filter(id=self.own_item.pk).update(
            name="my_updated"
        )
        self.assertEqual(results[0].name, "my_updated")

    def test_cannot_update_others(self):
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            ObjectLevelItemClient.objects.filter(id=self.other_item.pk).update(
                name="hijacked"
            )

    def test_can_delete_own(self):
        self.configure_as_user()
        count = ObjectLevelItemClient.objects.filter(id=self.own_item.pk).delete()
        self.assertEqual(count, 1)

    def test_cannot_delete_others(self):
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            ObjectLevelItemClient.objects.filter(id=self.other_item.pk).delete()

    def test_admin_can_update_any(self):
        self.configure_as_admin()
        results = ObjectLevelItemClient.objects.filter(id=self.other_item.pk).update(
            name="admin_updated"
        )
        self.assertEqual(results[0].name, "admin_updated")


# ===========================================================================
# Composed (two permissions)
# ===========================================================================

class TestComposedPermissions(SecurityTestBase):

    def setUp(self):
        super().setUp()
        # Items owned by user (visible via OwnerFilterPerm)
        self.own_low = ComposedItem.objects.create(
            name="own_low", value=50, secret="s1", owner="sec_user"
        )
        self.own_high = ComposedItem.objects.create(
            name="own_high", value=150, secret="s2", owner="sec_user"
        )
        # Public item with value >= 100 (visible via PublicReadPerm)
        self.public_item = ComposedItem.objects.create(
            name="public_item", value=200, secret="s3", owner="other_user"
        )
        # Hidden: not owned by user AND value < 100
        self.hidden_item = ComposedItem.objects.create(
            name="hidden_item", value=10, secret="s4", owner="other_user"
        )

    def test_sees_own_and_public(self):
        """User sees own items + public items (value >= 100)."""
        self.configure_as_user()
        results = ComposedItemClient.objects.order_by("id").fetch()
        names = {r.name for r in results}
        # own_low: owned by user (visible via OwnerFilterPerm)
        # own_high: owned by user AND value >= 100 (visible via both)
        # public_item: value >= 100 (visible via PublicReadPerm)
        # hidden_item: NOT owned AND value < 100 (hidden)
        self.assertIn("own_low", names)
        self.assertIn("own_high", names)
        self.assertIn("public_item", names)
        self.assertNotIn("hidden_item", names)

    def test_fields_union(self):
        """Visible fields are union of both permissions."""
        self.configure_as_user()
        # OwnerFilterPerm: {"id", "name", "value", "owner"}
        # PublicReadPerm: {"id", "name", "value", "secret"}
        # Union: {"id", "name", "value", "owner", "secret"}
        results = ComposedItemClient.objects.filter(id=self.own_low.pk).fetch()
        self.assertEqual(len(results), 1)
        d = results[0].to_dict()
        self.assertIn("name", d)
        self.assertIn("value", d)
        # Both owner and secret should be visible due to union
        self.assertIn("owner", d)
        self.assertIn("secret", d)

    def test_actions_union(self):
        """Actions are union: owner perm allows write, public perm only allows read.
        Combined, the user should be able to write (to their own items)."""
        self.configure_as_user()
        # User can update their own item
        results = ComposedItemClient.objects.filter(id=self.own_low.pk).update(name="updated_own")
        self.assertEqual(results[0].name, "updated_own")


# ===========================================================================
# Error types
# ===========================================================================

class TestErrorTypes(SecurityTestBase):

    def test_not_found_error_type(self):
        self.configure_as_admin()
        with self.assertRaises(NotFound):
            ReadOnlyItemClient.objects.get(id=999999)

    def test_permission_denied_error_type(self):
        self.configure_as_user()
        with self.assertRaises(PermissionDenied):
            ReadOnlyItemClient.objects.create(name="fail")

    def test_multiple_objects_returned_error_type(self):
        ReadOnlyItem.objects.create(name="dup_name", value=1)
        ReadOnlyItem.objects.create(name="dup_name", value=2)
        self.configure_as_user()
        with self.assertRaises(MultipleObjectsReturned):
            ReadOnlyItemClient.objects.get(name="dup_name")

    def test_validation_error_type(self):
        self.configure_as_admin()
        with self.assertRaises(ValidationError):
            # Passing a non-integer for value should trigger validation error
            ReadOnlyItemClient.objects.create(name="valid_err", value="not_an_int")
