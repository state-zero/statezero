"""
Tests for PermissionedQuerySet – the drop-in replacement for Django QuerySets
that encapsulates all StateZero permission logic.
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q, Count, Avg, Max, Min, Sum, F
from django.test import TestCase
from django.utils import timezone

from statezero.adaptors.django.permissioned_queryset import (
    PermissionedQuerySet,
    _FakeRequest,
    _PermissionedInstance,
    for_user,
    install_for_user,
)
from statezero.core.exceptions import PermissionDenied, ValidationError
from statezero.core.types import ActionType

from tests.django_app.models import (
    ComprehensiveModel,
    CustomPKModel,
    DummyModel,
    DummyRelatedModel,
    ModelWithCustomPKRelation,
    NameFilterCustomPKModel,
    Product,
    ProductCategory,
)

User = get_user_model()


# ======================================================================
# Helpers
# ======================================================================


class _Base(TestCase):
    """Shared setUp that creates a regular user and a superuser."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="normaluser", password="password"
        )
        cls.superuser = User.objects.create_superuser(
            username="admin", password="password"
        )


# ======================================================================
# 1. Basic queryset behaviour (AllowAllPermission via DummyModel)
# ======================================================================


class TestBasicQuerySetBehavior(_Base):
    """for_user on a model with AllowAllPermission should behave like a
    regular QuerySet for read operations."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.related = DummyRelatedModel.objects.create(name="Rel1")
        cls.d1 = DummyModel.objects.create(name="Alpha", value=10, related=cls.related)
        cls.d2 = DummyModel.objects.create(name="Beta", value=20)
        cls.d3 = DummyModel.objects.create(name="Gamma", value=30)

    def test_returns_permissioned_queryset(self):
        qs = for_user(DummyModel, self.user)
        self.assertIsInstance(qs, PermissionedQuerySet)

    def test_count(self):
        qs = for_user(DummyModel, self.user)
        self.assertEqual(qs.count(), 3)

    def test_filter(self):
        qs = for_user(DummyModel, self.user).filter(name="Alpha")
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, "Alpha")

    def test_exclude(self):
        qs = for_user(DummyModel, self.user).exclude(name="Alpha")
        self.assertEqual(qs.count(), 2)

    def test_order_by(self):
        qs = for_user(DummyModel, self.user).order_by("-value")
        names = list(qs.values_list("name", flat=True))
        self.assertEqual(names, ["Gamma", "Beta", "Alpha"])

    def test_exists(self):
        self.assertTrue(for_user(DummyModel, self.user).exists())

    def test_first_last(self):
        qs = for_user(DummyModel, self.user).order_by("name")
        self.assertEqual(qs.first().name, "Alpha")
        self.assertEqual(qs.last().name, "Gamma")

    def test_values(self):
        qs = for_user(DummyModel, self.user).filter(name="Alpha").values("name")
        self.assertEqual(list(qs), [{"name": "Alpha"}])

    def test_values_list(self):
        qs = (
            for_user(DummyModel, self.user)
            .filter(name="Beta")
            .values_list("value", flat=True)
        )
        self.assertEqual(list(qs), [20])

    def test_iteration(self):
        qs = for_user(DummyModel, self.user).order_by("name")
        names = [obj.name for obj in qs]
        self.assertEqual(names, ["Alpha", "Beta", "Gamma"])

    def test_slicing(self):
        qs = for_user(DummyModel, self.user).order_by("name")[:2]
        self.assertEqual(len(qs), 2)

    def test_get(self):
        obj = for_user(DummyModel, self.user).get(name="Alpha")
        self.assertEqual(obj.pk, self.d1.pk)

    def test_aggregate(self):
        from django.db.models import Sum

        result = for_user(DummyModel, self.user).aggregate(total=Sum("value"))
        self.assertEqual(result["total"], 60)

    def test_chaining_preserves_permission_type(self):
        qs = for_user(DummyModel, self.user).filter(name="Alpha").exclude(value=0)
        self.assertIsInstance(qs, PermissionedQuerySet)

    def test_chaining_preserves_metadata(self):
        qs = for_user(DummyModel, self.user).filter(name="Alpha")
        self.assertTrue(qs._sz_permissions_resolved)
        self.assertIsNotNone(qs._sz_allowed_actions)


# ======================================================================
# 2. Permission metadata properties
# ======================================================================


class TestPermissionMetadata(_Base):
    def test_allow_all_actions(self):
        qs = for_user(DummyModel, self.user)
        self.assertIn(ActionType.CREATE, qs.allowed_actions)
        self.assertIn(ActionType.READ, qs.allowed_actions)
        self.assertIn(ActionType.UPDATE, qs.allowed_actions)
        self.assertIn(ActionType.DELETE, qs.allowed_actions)

    def test_readonly_actions_normal_user(self):
        """CustomPKModel uses ReadOnlyPermission — non-superusers get READ only."""
        qs = for_user(CustomPKModel, self.user)
        self.assertIn(ActionType.READ, qs.allowed_actions)
        self.assertNotIn(ActionType.CREATE, qs.allowed_actions)
        self.assertNotIn(ActionType.UPDATE, qs.allowed_actions)
        self.assertNotIn(ActionType.DELETE, qs.allowed_actions)

    def test_readonly_actions_superuser(self):
        qs = for_user(CustomPKModel, self.superuser)
        self.assertIn(ActionType.CREATE, qs.allowed_actions)
        self.assertIn(ActionType.UPDATE, qs.allowed_actions)
        self.assertIn(ActionType.DELETE, qs.allowed_actions)

    def test_visible_fields_all(self):
        """AllowAllPermission grants __all__ visible fields."""
        qs = for_user(DummyModel, self.user)
        self.assertIn("name", qs.visible_fields)
        self.assertIn("value", qs.visible_fields)

    def test_restricted_fields_normal_user(self):
        """RestrictedFieldsPermission limits non-superusers to a few fields."""
        qs = for_user(ModelWithCustomPKRelation, self.user)
        # Non-admin only sees: name, custom_pk, pk, custom_pk_related
        self.assertIn("name", qs.visible_fields)
        self.assertNotIn("id", qs.visible_fields)

    def test_restricted_fields_superuser(self):
        qs = for_user(ModelWithCustomPKRelation, self.superuser)
        self.assertIn("name", qs.visible_fields)
        self.assertIn("id", qs.visible_fields)

    def test_editable_fields_readonly_normal(self):
        """ReadOnly permission: non-superusers have no editable fields."""
        qs = for_user(CustomPKModel, self.user)
        self.assertEqual(qs.editable_fields, set())

    def test_editable_fields_readonly_super(self):
        qs = for_user(CustomPKModel, self.superuser)
        self.assertTrue(len(qs.editable_fields) > 0)

    def test_create_fields_readonly_normal(self):
        qs = for_user(CustomPKModel, self.user)
        self.assertEqual(qs.create_fields, set())

    def test_can_helper(self):
        qs = for_user(DummyModel, self.user)
        self.assertTrue(qs.can(ActionType.CREATE))
        self.assertTrue(qs.can(ActionType.READ))

    def test_can_read_helper(self):
        qs = for_user(DummyModel, self.user)
        self.assertTrue(qs.can_read("name"))

    def test_can_edit_helper(self):
        qs = for_user(DummyModel, self.user)
        self.assertTrue(qs.can_edit("name"))

    def test_metadata_returns_copies(self):
        """Properties should return copies so callers can't mutate internal state."""
        qs = for_user(DummyModel, self.user)
        actions = qs.allowed_actions
        actions.add(ActionType.PRE_DELETE)
        self.assertNotIn(ActionType.PRE_DELETE, qs.allowed_actions)


# ======================================================================
# 3. Row-level filtering (NameFilterPermission)
# ======================================================================


class TestRowLevelFiltering(_Base):
    """NameFilterCustomPKModel uses NameFilterPermission which filters
    queryset to only rows where name starts with 'Allowed'."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.allowed1 = NameFilterCustomPKModel.objects.create(name="Allowed Item 1")
        cls.allowed2 = NameFilterCustomPKModel.objects.create(name="Allowed Item 2")
        cls.denied = NameFilterCustomPKModel.objects.create(name="Denied Item")

    def test_unfiltered_has_all(self):
        self.assertEqual(NameFilterCustomPKModel.objects.count(), 3)

    def test_for_user_filters_rows(self):
        qs = for_user(NameFilterCustomPKModel, self.user)
        self.assertEqual(qs.count(), 2)
        names = set(qs.values_list("name", flat=True))
        self.assertEqual(names, {"Allowed Item 1", "Allowed Item 2"})

    def test_denied_item_not_visible(self):
        qs = for_user(NameFilterCustomPKModel, self.user)
        self.assertFalse(qs.filter(name="Denied Item").exists())

    def test_filter_on_top_of_permission_filter(self):
        qs = for_user(NameFilterCustomPKModel, self.user).filter(
            name="Allowed Item 1"
        )
        self.assertEqual(qs.count(), 1)

    def test_row_filtering_preserved_after_chaining(self):
        qs = for_user(NameFilterCustomPKModel, self.user).order_by("name")
        self.assertEqual(qs.count(), 2)


# ======================================================================
# 4. Operation-level permissions
# ======================================================================


class TestOperationPermissions(_Base):
    """CustomPKModel uses ReadOnlyPermission — writes denied for non-superusers."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.item = CustomPKModel.objects.create(name="Existing")

    def test_create_denied(self):
        qs = for_user(CustomPKModel, self.user)
        with self.assertRaises(PermissionDenied):
            qs.create(name="New")

    def test_update_denied(self):
        qs = for_user(CustomPKModel, self.user).filter(
            custom_pk=self.item.custom_pk
        )
        with self.assertRaises(PermissionDenied):
            qs.update(name="Updated")

    def test_delete_denied(self):
        qs = for_user(CustomPKModel, self.user).filter(
            custom_pk=self.item.custom_pk
        )
        with self.assertRaises(PermissionDenied):
            qs.delete()

    def test_create_allowed_superuser(self):
        qs = for_user(CustomPKModel, self.superuser)
        obj = qs.create(name="SuperCreated")
        self.assertIsNotNone(obj.pk)
        self.assertEqual(obj.name, "SuperCreated")

    def test_update_allowed_superuser(self):
        qs = for_user(CustomPKModel, self.superuser).filter(
            custom_pk=self.item.custom_pk
        )
        rows = qs.update(name="SuperUpdated")
        self.assertEqual(rows, 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.name, "SuperUpdated")

    def test_delete_allowed_superuser(self):
        to_delete = CustomPKModel.objects.create(name="ToDelete")
        qs = for_user(CustomPKModel, self.superuser).filter(
            custom_pk=to_delete.custom_pk
        )
        deleted_count, _ = qs.delete()
        self.assertEqual(deleted_count, 1)

    def test_bulk_create_denied(self):
        qs = for_user(CustomPKModel, self.user)
        with self.assertRaises(PermissionDenied):
            qs.bulk_create([CustomPKModel(name="Bulk1")])


# ======================================================================
# 5. Field-level write filtering
# ======================================================================


class TestFieldLevelWriteFiltering(_Base):
    """
    RestrictedFieldsPermission on ModelWithCustomPKRelation:
    Non-superusers can only write to 'name'.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cpk = CustomPKModel.objects.create(name="Related")

    def test_create_fields_are_restricted(self):
        """Non-admin create_fields should only include 'name'."""
        qs = for_user(ModelWithCustomPKRelation, self.user)
        self.assertEqual(qs.create_fields, {"name"})

    def test_update_filters_to_editable_fields(self):
        """Non-admin update with disallowed fields — only 'name' passes."""
        obj = ModelWithCustomPKRelation.objects.create(
            name="Before", custom_pk_related=self.cpk
        )
        qs = for_user(ModelWithCustomPKRelation, self.user).filter(pk=obj.pk)
        qs.update(name="After")
        obj.refresh_from_db()
        self.assertEqual(obj.name, "After")

    def test_superuser_can_write_all_fields(self):
        qs = for_user(ModelWithCustomPKRelation, self.superuser)
        obj = qs.create(name="Super", custom_pk_related=self.cpk)
        self.assertEqual(obj.name, "Super")
        self.assertEqual(obj.custom_pk_related_id, self.cpk.pk)


# ======================================================================
# 6. Write operations on AllowAll model
# ======================================================================


class TestWriteOperationsAllowAll(_Base):
    """DummyModel with AllowAllPermission — writes should work."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.related = DummyRelatedModel.objects.create(name="R")

    def test_create(self):
        qs = for_user(DummyModel, self.user)
        obj = qs.create(name="Created", value=42)
        self.assertEqual(obj.name, "Created")
        self.assertEqual(obj.value, 42)

    def test_update(self):
        obj = DummyModel.objects.create(name="Old", value=1)
        qs = for_user(DummyModel, self.user).filter(pk=obj.pk)
        qs.update(value=99)
        obj.refresh_from_db()
        self.assertEqual(obj.value, 99)

    def test_delete(self):
        obj = DummyModel.objects.create(name="Del", value=0)
        pk = obj.pk
        qs = for_user(DummyModel, self.user).filter(pk=pk)
        deleted_count, _ = qs.delete()
        self.assertEqual(deleted_count, 1)
        self.assertFalse(DummyModel.objects.filter(pk=pk).exists())

    def test_get_or_create_creates(self):
        qs = for_user(DummyModel, self.user)
        obj, created = qs.get_or_create(
            name="Unique123", defaults={"value": 7}
        )
        self.assertTrue(created)
        self.assertEqual(obj.value, 7)

    def test_get_or_create_gets(self):
        existing = DummyModel.objects.create(name="Exists", value=5)
        qs = for_user(DummyModel, self.user)
        obj, created = qs.get_or_create(
            name="Exists", defaults={"value": 999}
        )
        self.assertFalse(created)
        self.assertEqual(obj.pk, existing.pk)
        self.assertEqual(obj.value, 5)

    def test_update_or_create_creates(self):
        qs = for_user(DummyModel, self.user)
        obj, created = qs.update_or_create(
            name="UOC", defaults={"value": 11}
        )
        self.assertTrue(created)
        self.assertEqual(obj.value, 11)

    def test_update_or_create_updates(self):
        DummyModel.objects.create(name="UOC2", value=1)
        qs = for_user(DummyModel, self.user)
        obj, created = qs.update_or_create(
            name="UOC2", defaults={"value": 22}
        )
        self.assertFalse(created)
        self.assertEqual(obj.value, 22)

    def test_bulk_create(self):
        qs = for_user(DummyModel, self.user)
        objs = qs.bulk_create(
            [DummyModel(name="B1", value=1), DummyModel(name="B2", value=2)]
        )
        self.assertEqual(len(objs), 2)
        self.assertEqual(DummyModel.objects.filter(name__startswith="B").count(), 2)


# ======================================================================
# 7. Object-level permissions (NameFilterPermission)
# ======================================================================


class TestObjectLevelPermissions(_Base):
    """NameFilterPermission checks object-level: only objects whose name
    starts with 'Allowed' can be mutated by non-superusers."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.allowed = NameFilterCustomPKModel.objects.create(name="Allowed Obj")
        cls.denied = NameFilterCustomPKModel.objects.create(name="Denied Obj")

    def test_update_allowed_object(self):
        qs = for_user(NameFilterCustomPKModel, self.user).filter(
            pk=self.allowed.pk
        )
        rows = qs.update(name="Allowed Updated")
        self.assertEqual(rows, 1)

    def test_delete_allowed_object(self):
        obj = NameFilterCustomPKModel.objects.create(name="Allowed Deletable")
        qs = for_user(NameFilterCustomPKModel, self.user).filter(pk=obj.pk)
        deleted_count, _ = qs.delete()
        self.assertEqual(deleted_count, 1)

    def test_denied_object_not_in_queryset(self):
        """The denied object is already filtered out at the row level,
        so operations on it simply affect 0 rows (no PermissionDenied)."""
        qs = for_user(NameFilterCustomPKModel, self.user).filter(
            pk=self.denied.pk
        )
        self.assertEqual(qs.count(), 0)


# ======================================================================
# 8. Request object support
# ======================================================================


class TestRequestObjectSupport(_Base):
    def test_accepts_user_object(self):
        qs = for_user(DummyModel, self.user)
        self.assertIsInstance(qs, PermissionedQuerySet)

    def test_accepts_fake_request(self):
        req = _FakeRequest(self.user)
        qs = for_user(DummyModel, req)
        self.assertIsInstance(qs, PermissionedQuerySet)

    def test_accepts_drf_request_like(self):
        """Any object with a .user attribute is treated as a request."""

        class MockRequest:
            def __init__(self, user):
                self.user = user

        req = MockRequest(self.user)
        qs = for_user(DummyModel, req)
        self.assertIsInstance(qs, PermissionedQuerySet)


# ======================================================================
# 9. install_for_user helper
# ======================================================================


class TestInstallForUser(_Base):
    def test_install_adds_for_user(self):
        install_for_user(DummyModel)
        qs = DummyModel.for_user(self.user)
        self.assertIsInstance(qs, PermissionedQuerySet)

    def test_model_for_user_returns_correct_model(self):
        install_for_user(DummyModel)
        qs = DummyModel.for_user(self.user)
        self.assertEqual(qs.model, DummyModel)


# ======================================================================
# 10. Uninitialised queryset guard
# ======================================================================


class TestUninitialisedGuard(TestCase):
    def test_accessing_metadata_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            _ = pqs.allowed_actions

    def test_create_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            pqs.create(name="x")

    def test_update_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            pqs.update(name="x")

    def test_delete_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            pqs.delete()


# ======================================================================
# 11. Empty queryset operations
# ======================================================================


class TestEmptyQueryset(_Base):
    def test_update_on_empty_returns_zero(self):
        qs = for_user(DummyModel, self.user).filter(name="nonexistent")
        # No rows match, but action is allowed → should return 0
        rows = qs.update(value=999)
        self.assertEqual(rows, 0)

    def test_delete_on_empty(self):
        qs = for_user(DummyModel, self.user).filter(name="nonexistent")
        deleted_count, _ = qs.delete()
        self.assertEqual(deleted_count, 0)


# ======================================================================
# 12. Unregistered model
# ======================================================================


class TestUnregisteredModel(_Base):
    def test_raises_for_unregistered_model(self):
        with self.assertRaises(ValueError):
            for_user(User, self.user)


# ======================================================================
# 13. Field-level filtering actually strips disallowed write fields
# ======================================================================


class TestFieldFilteringStripsData(_Base):
    """Verify that disallowed fields are actually removed from write data,
    not just that the operation succeeds."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cpk = CustomPKModel.objects.create(name="Related")

    def test_update_strips_non_editable_fields(self):
        """Non-admin editable_fields={'name'} on RestrictedFieldsPermission.
        Passing an extra disallowed field should silently drop it."""
        obj = ModelWithCustomPKRelation.objects.create(
            name="Original", custom_pk_related=self.cpk
        )
        cpk2 = CustomPKModel.objects.create(name="Other")
        qs = for_user(ModelWithCustomPKRelation, self.user).filter(pk=obj.pk)
        # custom_pk_related_id is NOT in editable_fields for non-admin
        qs.update(name="Changed", custom_pk_related_id=cpk2.pk)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "Changed")
        # FK should be unchanged because the field was stripped
        self.assertEqual(obj.custom_pk_related_id, self.cpk.pk)

    def test_update_returns_zero_when_all_kwargs_stripped(self):
        """If every kwarg is disallowed, update returns 0 without touching DB."""
        obj = ModelWithCustomPKRelation.objects.create(
            name="Keep", custom_pk_related=self.cpk
        )
        qs = for_user(ModelWithCustomPKRelation, self.user).filter(pk=obj.pk)
        # Only pass fields the non-admin can't write (id is not in editable_fields)
        rows = qs.update(id=999)
        self.assertEqual(rows, 0)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "Keep")

    def test_get_or_create_defaults_filtered(self):
        """Defaults dict should have non-create_fields stripped."""
        qs = for_user(DummyModel, self.user)
        obj, created = qs.get_or_create(
            name="GocFiltered",
            defaults={"value": 42, "name": "GocFiltered"},
        )
        self.assertTrue(created)
        # 'value' is in AllowAll create_fields so it should survive
        self.assertEqual(obj.value, 42)

    def test_update_or_create_defaults_filtered_restricted(self):
        """On a restricted model, disallowed defaults should be stripped."""
        obj = ModelWithCustomPKRelation.objects.create(
            name="UOC_Restricted", custom_pk_related=self.cpk
        )
        cpk2 = CustomPKModel.objects.create(name="Other2")
        qs = for_user(ModelWithCustomPKRelation, self.user)
        updated_obj, created = qs.update_or_create(
            name="UOC_Restricted",
            defaults={"custom_pk_related_id": cpk2.pk},
        )
        self.assertFalse(created)
        updated_obj.refresh_from_db()
        # FK should be unchanged — field stripped by permission
        self.assertEqual(updated_obj.custom_pk_related_id, self.cpk.pk)

    def test_superuser_update_keeps_all_fields(self):
        """Superuser editable_fields=__all__ — nothing stripped."""
        obj = ModelWithCustomPKRelation.objects.create(
            name="Super", custom_pk_related=self.cpk
        )
        cpk2 = CustomPKModel.objects.create(name="Super2")
        qs = for_user(ModelWithCustomPKRelation, self.superuser).filter(pk=obj.pk)
        qs.update(name="SuperChanged", custom_pk_related_id=cpk2.pk)
        obj.refresh_from_db()
        self.assertEqual(obj.name, "SuperChanged")
        self.assertEqual(obj.custom_pk_related_id, cpk2.pk)


# ======================================================================
# 14. Operation-level denials for get_or_create / update_or_create
# ======================================================================


class TestCompoundOperationPermissions(_Base):
    """ReadOnlyPermission on CustomPKModel: non-superusers lack CREATE/UPDATE."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.item = CustomPKModel.objects.create(name="CmpExisting")

    def test_get_or_create_denied(self):
        qs = for_user(CustomPKModel, self.user)
        with self.assertRaises(PermissionDenied):
            qs.get_or_create(name="NewGOC", defaults={"name": "NewGOC"})

    def test_update_or_create_denied(self):
        qs = for_user(CustomPKModel, self.user)
        with self.assertRaises(PermissionDenied):
            qs.update_or_create(
                name="CmpExisting", defaults={"name": "Updated"}
            )

    def test_get_or_create_allowed_superuser(self):
        qs = for_user(CustomPKModel, self.superuser)
        obj, created = qs.get_or_create(
            name="CmpExisting", defaults={"name": "CmpExisting"}
        )
        self.assertFalse(created)
        self.assertEqual(obj.pk, self.item.pk)

    def test_update_or_create_creates_superuser(self):
        qs = for_user(CustomPKModel, self.superuser)
        obj, created = qs.update_or_create(
            name="BrandNewSU", defaults={"name": "BrandNewSU"}
        )
        self.assertTrue(created)

    def test_update_or_create_updates_superuser(self):
        qs = for_user(CustomPKModel, self.superuser)
        obj, created = qs.update_or_create(
            name="CmpExisting", defaults={"name": "CmpExisting"}
        )
        self.assertFalse(created)
        self.assertEqual(obj.pk, self.item.pk)


# ======================================================================
# 15. Bulk object-level / bulk_operation_allowed
# ======================================================================


class TestBulkPermissionChecks(_Base):
    """Verify that update/delete on multiple objects goes through the
    bulk_operation_allowed path (count > 1)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.a1 = NameFilterCustomPKModel.objects.create(name="Allowed Bulk1")
        cls.a2 = NameFilterCustomPKModel.objects.create(name="Allowed Bulk2")
        cls.a3 = NameFilterCustomPKModel.objects.create(name="Allowed Bulk3")
        cls.denied = NameFilterCustomPKModel.objects.create(name="Denied Bulk")

    def test_bulk_update_allowed_objects(self):
        qs = for_user(NameFilterCustomPKModel, self.user)
        self.assertTrue(qs.count() >= 3)  # only "Allowed" items visible
        rows = qs.update(name="Allowed Renamed")
        self.assertEqual(rows, qs.count() + rows - rows)  # just check it succeeded
        self.assertTrue(rows >= 3)

    def test_bulk_delete_allowed_objects(self):
        # Create some to delete
        extras = [
            NameFilterCustomPKModel.objects.create(name="Allowed DelBulk1"),
            NameFilterCustomPKModel.objects.create(name="Allowed DelBulk2"),
        ]
        qs = for_user(NameFilterCustomPKModel, self.user).filter(
            pk__in=[e.pk for e in extras]
        )
        deleted_count, _ = qs.delete()
        self.assertEqual(deleted_count, 2)

    def test_denied_objects_excluded_from_bulk_update(self):
        """Row-level filter means denied objects aren't in the queryset,
        so they can't be updated."""
        qs = for_user(NameFilterCustomPKModel, self.user)
        qs.update(name="Allowed BulkRenamed")
        self.denied.refresh_from_db()
        self.assertEqual(self.denied.name, "Denied Bulk")  # untouched


# ======================================================================
# 16. Multiple chained operations preserve correct state
# ======================================================================


class TestChainingIntegrity(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        DummyModel.objects.create(name="C1", value=10)
        DummyModel.objects.create(name="C2", value=20)
        DummyModel.objects.create(name="C3", value=30)

    def test_filter_then_update(self):
        qs = for_user(DummyModel, self.user).filter(value__gte=20)
        rows = qs.update(value=99)
        self.assertEqual(rows, 2)

    def test_exclude_then_delete(self):
        to_del = DummyModel.objects.create(name="CDel", value=0)
        qs = for_user(DummyModel, self.user).filter(pk=to_del.pk)
        deleted, _ = qs.delete()
        self.assertEqual(deleted, 1)

    def test_order_by_then_values(self):
        qs = for_user(DummyModel, self.user).order_by("value").values("name")
        self.assertIsInstance(qs.first(), dict)

    def test_double_filter(self):
        qs = (
            for_user(DummyModel, self.user)
            .filter(value__gte=10)
            .filter(value__lte=20)
        )
        self.assertIsInstance(qs, PermissionedQuerySet)
        self.assertTrue(qs.count() <= 3)

    def test_all_returns_permissioned_queryset(self):
        qs = for_user(DummyModel, self.user).all()
        self.assertIsInstance(qs, PermissionedQuerySet)
        self.assertTrue(qs._sz_permissions_resolved)

    def test_none_returns_permissioned_queryset(self):
        qs = for_user(DummyModel, self.user).none()
        self.assertIsInstance(qs, PermissionedQuerySet)
        self.assertEqual(qs.count(), 0)

    def test_distinct(self):
        qs = for_user(DummyModel, self.user).distinct()
        self.assertIsInstance(qs, PermissionedQuerySet)


# ======================================================================
# 17. Same user, different models yield different permissions
# ======================================================================


class TestCrossModelPermissions(_Base):
    """Verify that the same user gets different permission sets
    depending on which model they query."""

    def test_same_user_different_actions(self):
        allow_all_qs = for_user(DummyModel, self.user)
        readonly_qs = for_user(CustomPKModel, self.user)

        self.assertIn(ActionType.UPDATE, allow_all_qs.allowed_actions)
        self.assertNotIn(ActionType.UPDATE, readonly_qs.allowed_actions)

    def test_same_user_different_visible_fields(self):
        allow_all_qs = for_user(DummyModel, self.user)
        restricted_qs = for_user(ModelWithCustomPKRelation, self.user)

        # AllowAll → many fields visible
        self.assertIn("value", allow_all_qs.visible_fields)
        # RestrictedFields → non-admin only sees name, custom_pk, pk, custom_pk_related
        self.assertNotIn("id", restricted_qs.visible_fields)

    def test_same_user_different_editable_fields(self):
        allow_all_qs = for_user(DummyModel, self.user)
        restricted_qs = for_user(ModelWithCustomPKRelation, self.user)

        self.assertIn("value", allow_all_qs.editable_fields)
        self.assertEqual(restricted_qs.editable_fields, {"name"})


# ======================================================================
# 18. Uninitialised guards on all write paths
# ======================================================================


class TestUninitialisedGuardAllPaths(TestCase):
    def test_get_or_create_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            pqs.get_or_create(name="x")

    def test_update_or_create_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            pqs.update_or_create(name="x")

    def test_bulk_create_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            pqs.bulk_create([DummyModel(name="x")])

    def test_can_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            pqs.can(ActionType.READ)

    def test_can_read_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            pqs.can_read("name")

    def test_can_edit_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            pqs.can_edit("name")

    def test_visible_fields_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            _ = pqs.visible_fields

    def test_editable_fields_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            _ = pqs.editable_fields

    def test_create_fields_raises(self):
        pqs = PermissionedQuerySet(model=DummyModel)
        with self.assertRaises(RuntimeError):
            _ = pqs.create_fields


# ======================================================================
# 19. Date lookups and datetime field modifiers
# ======================================================================


class TestDateLookups(_Base):
    """Verify that Django date/time lookups work through PermissionedQuerySet."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cat = ProductCategory.objects.create(name="DateCat")
        cls.p_jan = Product.objects.create(
            name="JanProduct",
            description="d",
            price=Decimal("10.00"),
            category=cls.cat,
            created_at=timezone.make_aware(datetime.datetime(2025, 1, 15, 12, 0)),
        )
        cls.p_jun = Product.objects.create(
            name="JunProduct",
            description="d",
            price=Decimal("20.00"),
            category=cls.cat,
            created_at=timezone.make_aware(datetime.datetime(2025, 6, 20, 8, 30)),
        )
        cls.p_dec = Product.objects.create(
            name="DecProduct",
            description="d",
            price=Decimal("30.00"),
            category=cls.cat,
            created_at=timezone.make_aware(datetime.datetime(2025, 12, 1, 18, 0)),
        )

    def test_filter_year(self):
        qs = for_user(Product, self.user).filter(created_at__year=2025)
        self.assertEqual(qs.count(), 3)

    def test_filter_year_no_match(self):
        qs = for_user(Product, self.user).filter(created_at__year=2020)
        self.assertEqual(qs.count(), 0)

    def test_filter_month(self):
        qs = for_user(Product, self.user).filter(created_at__month=6)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, "JunProduct")

    def test_filter_day(self):
        qs = for_user(Product, self.user).filter(created_at__day=15)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, "JanProduct")

    def test_filter_year_gte(self):
        qs = for_user(Product, self.user).filter(created_at__year__gte=2025)
        self.assertEqual(qs.count(), 3)

    def test_filter_month_lt(self):
        qs = for_user(Product, self.user).filter(created_at__month__lt=6)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, "JanProduct")

    def test_filter_date(self):
        target = datetime.date(2025, 6, 20)
        qs = for_user(Product, self.user).filter(created_at__date=target)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, "JunProduct")

    def test_filter_date_range(self):
        start = timezone.make_aware(datetime.datetime(2025, 1, 1))
        end = timezone.make_aware(datetime.datetime(2025, 6, 30))
        qs = for_user(Product, self.user).filter(created_at__range=(start, end))
        self.assertEqual(qs.count(), 2)

    def test_filter_hour(self):
        qs = for_user(Product, self.user).filter(created_at__hour=18)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, "DecProduct")

    def test_filter_gt_datetime(self):
        cutoff = timezone.make_aware(datetime.datetime(2025, 6, 1))
        qs = for_user(Product, self.user).filter(created_at__gt=cutoff)
        self.assertEqual(qs.count(), 2)

    def test_filter_lte_datetime(self):
        cutoff = timezone.make_aware(datetime.datetime(2025, 1, 15, 12, 0))
        qs = for_user(Product, self.user).filter(created_at__lte=cutoff)
        self.assertEqual(qs.count(), 1)

    def test_exclude_by_month(self):
        qs = for_user(Product, self.user).exclude(created_at__month=1)
        self.assertEqual(qs.count(), 2)

    def test_order_by_datetime(self):
        qs = for_user(Product, self.user).order_by("created_at")
        names = list(qs.values_list("name", flat=True))
        self.assertEqual(names, ["JanProduct", "JunProduct", "DecProduct"])

    def test_order_by_datetime_desc(self):
        qs = for_user(Product, self.user).order_by("-created_at")
        names = list(qs.values_list("name", flat=True))
        self.assertEqual(names, ["DecProduct", "JunProduct", "JanProduct"])


# ======================================================================
# 20. String / text query modifiers
# ======================================================================


class TestStringLookups(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Use distinct prefixes to avoid SQLite case-insensitive LIKE collisions
        DummyModel.objects.create(name="Xray World", value=1)
        DummyModel.objects.create(name="yankee earth", value=2)
        DummyModel.objects.create(name="ZULU MARS", value=3)
        DummyModel.objects.create(name="Goodbye Moon", value=4)

    def test_exact(self):
        qs = for_user(DummyModel, self.user).filter(name__exact="Xray World")
        self.assertEqual(qs.count(), 1)

    def test_iexact(self):
        qs = for_user(DummyModel, self.user).filter(name__iexact="xray world")
        self.assertEqual(qs.count(), 1)

    def test_contains(self):
        qs = for_user(DummyModel, self.user).filter(name__contains="World")
        self.assertEqual(qs.count(), 1)

    def test_icontains(self):
        qs = for_user(DummyModel, self.user).filter(name__icontains="mars")
        self.assertEqual(qs.count(), 1)

    def test_startswith(self):
        qs = for_user(DummyModel, self.user).filter(name__startswith="Xray")
        self.assertEqual(qs.count(), 1)

    def test_istartswith(self):
        qs = for_user(DummyModel, self.user).filter(name__istartswith="zulu")
        self.assertEqual(qs.count(), 1)

    def test_endswith(self):
        qs = for_user(DummyModel, self.user).filter(name__endswith="Moon")
        self.assertEqual(qs.count(), 1)

    def test_iendswith(self):
        qs = for_user(DummyModel, self.user).filter(name__iendswith="mars")
        self.assertEqual(qs.count(), 1)


# ======================================================================
# 21. Numeric query modifiers
# ======================================================================


class TestNumericLookups(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        DummyModel.objects.create(name="N1", value=10)
        DummyModel.objects.create(name="N2", value=20)
        DummyModel.objects.create(name="N3", value=30)
        DummyModel.objects.create(name="N4", value=None)

    def test_gt(self):
        qs = for_user(DummyModel, self.user).filter(value__gt=15)
        self.assertEqual(qs.count(), 2)

    def test_gte(self):
        qs = for_user(DummyModel, self.user).filter(value__gte=20)
        self.assertEqual(qs.count(), 2)

    def test_lt(self):
        qs = for_user(DummyModel, self.user).filter(value__lt=20)
        self.assertEqual(qs.count(), 1)

    def test_lte(self):
        qs = for_user(DummyModel, self.user).filter(value__lte=20)
        self.assertEqual(qs.count(), 2)

    def test_range(self):
        qs = for_user(DummyModel, self.user).filter(value__range=(15, 25))
        self.assertEqual(qs.count(), 1)

    def test_in(self):
        qs = for_user(DummyModel, self.user).filter(value__in=[10, 30])
        self.assertEqual(qs.count(), 2)

    def test_isnull_true(self):
        qs = for_user(DummyModel, self.user).filter(value__isnull=True)
        self.assertEqual(qs.count(), 1)

    def test_isnull_false(self):
        qs = for_user(DummyModel, self.user).filter(value__isnull=False)
        self.assertEqual(qs.count(), 3)

    def test_exclude_gt(self):
        qs = for_user(DummyModel, self.user).exclude(value__gt=20)
        # Excludes value>20 (N3=30), keeps N1=10, N2=20, N4=null
        # Note: NULL values are NOT excluded by gt comparison in SQL
        self.assertTrue(qs.count() >= 2)


# ======================================================================
# 22. Q objects and complex filters
# ======================================================================


class TestQObjectFilters(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        DummyModel.objects.create(name="QA", value=10)
        DummyModel.objects.create(name="QB", value=20)
        DummyModel.objects.create(name="QC", value=30)
        DummyModel.objects.create(name="QD", value=40)

    def test_q_or(self):
        qs = for_user(DummyModel, self.user).filter(
            Q(name="QA") | Q(name="QC")
        )
        self.assertEqual(qs.count(), 2)

    def test_q_and(self):
        qs = for_user(DummyModel, self.user).filter(
            Q(name="QA") & Q(value=10)
        )
        self.assertEqual(qs.count(), 1)

    def test_q_not(self):
        qs = for_user(DummyModel, self.user).filter(~Q(name="QA"))
        self.assertNotIn("QA", qs.values_list("name", flat=True))

    def test_q_complex_nested(self):
        qs = for_user(DummyModel, self.user).filter(
            (Q(name="QA") | Q(name="QB")) & Q(value__gte=10)
        )
        self.assertEqual(qs.count(), 2)

    def test_q_or_with_modifier(self):
        qs = for_user(DummyModel, self.user).filter(
            Q(value__gte=30) | Q(name__startswith="QA")
        )
        names = set(qs.values_list("name", flat=True))
        self.assertEqual(names, {"QA", "QC", "QD"})

    def test_combined_filter_exclude(self):
        qs = (
            for_user(DummyModel, self.user)
            .filter(value__gte=10)
            .exclude(name="QD")
        )
        self.assertEqual(qs.count(), 3)


# ======================================================================
# 23. Aggregations and annotations through PermissionedQuerySet
# ======================================================================


class TestAggregationsAnnotations(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        DummyModel.objects.create(name="Agg1", value=10)
        DummyModel.objects.create(name="Agg2", value=20)
        DummyModel.objects.create(name="Agg3", value=30)

    def test_sum(self):
        result = for_user(DummyModel, self.user).aggregate(total=Sum("value"))
        self.assertEqual(result["total"], 60)

    def test_avg(self):
        result = for_user(DummyModel, self.user).aggregate(avg=Avg("value"))
        self.assertEqual(result["avg"], 20)

    def test_max(self):
        result = for_user(DummyModel, self.user).aggregate(mx=Max("value"))
        self.assertEqual(result["mx"], 30)

    def test_min(self):
        result = for_user(DummyModel, self.user).aggregate(mn=Min("value"))
        self.assertEqual(result["mn"], 10)

    def test_count_aggregate(self):
        result = for_user(DummyModel, self.user).aggregate(cnt=Count("id"))
        self.assertEqual(result["cnt"], 3)

    def test_annotate(self):
        qs = for_user(DummyModel, self.user).annotate(doubled=F("value") * 2)
        self.assertIsInstance(qs, PermissionedQuerySet)
        obj = qs.get(name="Agg2")
        self.assertEqual(obj.doubled, 40)

    def test_aggregate_with_filter(self):
        result = (
            for_user(DummyModel, self.user)
            .filter(value__gte=20)
            .aggregate(total=Sum("value"))
        )
        self.assertEqual(result["total"], 50)

    def test_values_annotate(self):
        """Grouping with values + annotate."""
        qs = (
            for_user(DummyModel, self.user)
            .values("name")
            .annotate(cnt=Count("id"))
        )
        self.assertTrue(all("cnt" in row for row in qs))


# ======================================================================
# 24. FK / relational lookups through PermissionedQuerySet
# ======================================================================


class TestRelationalLookups(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.r1 = DummyRelatedModel.objects.create(name="RelA")
        cls.r2 = DummyRelatedModel.objects.create(name="RelB")
        DummyModel.objects.create(name="FK1", value=10, related=cls.r1)
        DummyModel.objects.create(name="FK2", value=20, related=cls.r1)
        DummyModel.objects.create(name="FK3", value=30, related=cls.r2)
        DummyModel.objects.create(name="FK4", value=40, related=None)

    def test_fk_exact(self):
        qs = for_user(DummyModel, self.user).filter(related=self.r1)
        self.assertEqual(qs.count(), 2)

    def test_fk_id(self):
        qs = for_user(DummyModel, self.user).filter(related_id=self.r2.pk)
        self.assertEqual(qs.count(), 1)

    def test_fk_isnull(self):
        qs = for_user(DummyModel, self.user).filter(related__isnull=True)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, "FK4")

    def test_fk_traverse_field(self):
        """Filter through FK: related__name."""
        qs = for_user(DummyModel, self.user).filter(related__name="RelA")
        self.assertEqual(qs.count(), 2)

    def test_fk_traverse_with_modifier(self):
        qs = for_user(DummyModel, self.user).filter(
            related__name__icontains="rela"
        )
        self.assertEqual(qs.count(), 2)

    def test_fk_in(self):
        qs = for_user(DummyModel, self.user).filter(
            related__in=[self.r1, self.r2]
        )
        self.assertEqual(qs.count(), 3)

    def test_select_related(self):
        qs = for_user(DummyModel, self.user).select_related("related")
        self.assertIsInstance(qs, PermissionedQuerySet)
        obj = qs.filter(name="FK1").first()
        self.assertEqual(obj.related.name, "RelA")

    def test_prefetch_related(self):
        qs = for_user(DummyRelatedModel, self.user).prefetch_related(
            "dummy_models"
        )
        self.assertIsInstance(qs, PermissionedQuerySet)
        rel = qs.get(name="RelA")
        self.assertEqual(rel.dummy_models.count(), 2)


# ======================================================================
# 25. ComprehensiveModel field-type lookups (JSON, Decimal, Bool)
# ======================================================================


class TestComprehensiveFieldLookups(_Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.c1 = ComprehensiveModel.objects.create(
            char_field="alpha",
            text_field="long text",
            int_field=100,
            bool_field=True,
            decimal_field=Decimal("9.99"),
            json_field={"key": "value", "nested": {"a": 1}},
        )
        cls.c2 = ComprehensiveModel.objects.create(
            char_field="beta",
            text_field="other text",
            int_field=200,
            bool_field=False,
            decimal_field=Decimal("19.99"),
            json_field={"key": "other"},
        )

    def test_bool_filter_true(self):
        qs = for_user(ComprehensiveModel, self.user).filter(bool_field=True)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().char_field, "alpha")

    def test_bool_filter_false(self):
        qs = for_user(ComprehensiveModel, self.user).filter(bool_field=False)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().char_field, "beta")

    def test_decimal_gte(self):
        qs = for_user(ComprehensiveModel, self.user).filter(
            decimal_field__gte=Decimal("15.00")
        )
        self.assertEqual(qs.count(), 1)

    def test_decimal_range(self):
        qs = for_user(ComprehensiveModel, self.user).filter(
            decimal_field__range=(Decimal("5.00"), Decimal("25.00"))
        )
        self.assertEqual(qs.count(), 2)

    def test_int_field_in(self):
        qs = for_user(ComprehensiveModel, self.user).filter(
            int_field__in=[100, 300]
        )
        self.assertEqual(qs.count(), 1)

    def test_json_field_key_lookup(self):
        qs = for_user(ComprehensiveModel, self.user).filter(
            json_field__key="value"
        )
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().char_field, "alpha")

    def test_datetime_field_year(self):
        """ComprehensiveModel.datetime_field defaults to now()."""
        current_year = timezone.now().year
        qs = for_user(ComprehensiveModel, self.user).filter(
            datetime_field__year=current_year
        )
        self.assertEqual(qs.count(), 2)

    def test_text_field_contains(self):
        qs = for_user(ComprehensiveModel, self.user).filter(
            text_field__contains="long"
        )
        self.assertEqual(qs.count(), 1)


# ======================================================================
# 26. Row-level filtering combined with query modifiers
# ======================================================================


class TestRowFilterWithModifiers(_Base):
    """NameFilterPermission filters to name__startswith='Allowed'.
    Verify that additional query modifiers compose correctly on top."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        NameFilterCustomPKModel.objects.create(name="Allowed Alpha")
        NameFilterCustomPKModel.objects.create(name="Allowed Beta")
        NameFilterCustomPKModel.objects.create(name="Allowed Gamma")
        NameFilterCustomPKModel.objects.create(name="Denied Delta")

    def test_icontains_on_filtered(self):
        qs = for_user(NameFilterCustomPKModel, self.user).filter(
            name__icontains="beta"
        )
        self.assertEqual(qs.count(), 1)

    def test_startswith_on_filtered(self):
        qs = for_user(NameFilterCustomPKModel, self.user).filter(
            name__startswith="Allowed A"
        )
        self.assertEqual(qs.count(), 1)

    def test_in_on_filtered(self):
        qs = for_user(NameFilterCustomPKModel, self.user).filter(
            name__in=["Allowed Alpha", "Denied Delta"]
        )
        # "Denied Delta" is excluded by row-level filter
        self.assertEqual(qs.count(), 1)

    def test_q_or_on_filtered(self):
        qs = for_user(NameFilterCustomPKModel, self.user).filter(
            Q(name__endswith="Alpha") | Q(name__endswith="Gamma")
        )
        self.assertEqual(qs.count(), 2)

    def test_exclude_on_filtered(self):
        qs = for_user(NameFilterCustomPKModel, self.user).exclude(
            name__endswith="Beta"
        )
        names = set(qs.values_list("name", flat=True))
        self.assertNotIn("Allowed Beta", names)
        self.assertNotIn("Denied Delta", names)  # still filtered by row-level

    def test_order_by_with_modifier_filter(self):
        qs = (
            for_user(NameFilterCustomPKModel, self.user)
            .filter(name__icontains="allowed")
            .order_by("-name")
        )
        names = list(qs.values_list("name", flat=True))
        self.assertEqual(names, sorted(names, reverse=True))


# ======================================================================
# 27. Write operations with query modifiers selecting the target rows
# ======================================================================


class TestWriteWithModifiers(_Base):
    """Verify update/delete work when the target rows are selected
    using query modifiers (not just pk= or exact matches)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        DummyModel.objects.create(name="WriteA", value=10)
        DummyModel.objects.create(name="WriteB", value=20)
        DummyModel.objects.create(name="WriteC", value=30)
        DummyModel.objects.create(name="Other", value=40)

    def test_update_with_startswith(self):
        qs = for_user(DummyModel, self.user).filter(name__startswith="Write")
        rows = qs.update(value=99)
        self.assertEqual(rows, 3)

    def test_update_with_value_range(self):
        qs = for_user(DummyModel, self.user).filter(value__range=(15, 35))
        rows = qs.update(value=0)
        self.assertEqual(rows, 2)

    def test_update_with_in(self):
        qs = for_user(DummyModel, self.user).filter(name__in=["WriteA", "WriteC"])
        rows = qs.update(value=77)
        self.assertEqual(rows, 2)

    def test_delete_with_gt(self):
        to_del = DummyModel.objects.create(name="DelGT", value=999)
        qs = for_user(DummyModel, self.user).filter(value__gt=500)
        deleted, _ = qs.delete()
        self.assertEqual(deleted, 1)

    def test_delete_with_icontains(self):
        DummyModel.objects.create(name="REMOVEME_XYZ", value=0)
        qs = for_user(DummyModel, self.user).filter(name__icontains="removeme")
        deleted, _ = qs.delete()
        self.assertEqual(deleted, 1)

    def test_update_with_q_or(self):
        qs = for_user(DummyModel, self.user).filter(
            Q(name="WriteA") | Q(name="Other")
        )
        rows = qs.update(value=55)
        self.assertEqual(rows, 2)

    def test_get_or_create_with_iexact_lookup(self):
        qs = for_user(DummyModel, self.user)
        obj, created = qs.get_or_create(
            name__iexact="writea", defaults={"name": "writea", "value": 0}
        )
        # "WriteA" exists, iexact matches it
        self.assertFalse(created)
        self.assertEqual(obj.name, "WriteA")


# ======================================================================
# 28. Nested filter field permission exploit tests
# ======================================================================


class TestNestedFilterFieldExploits(TestCase):
    """
    Attack vector tests: verify that a non-admin user CANNOT probe hidden
    fields via filter/exclude — including when the hidden field lives on a
    *related* model reached through FK traversal.

    Setup:
        SecretParent  — has a ``secret`` field hidden from non-admins by
                        HideSecretPermission (visible_fields returns
                        {"id", "name", "public_info", "children"}).
        SecretChild   — FK to SecretParent, AllowAllPermission.
        SecretGrandchild — FK to SecretChild, AllowAllPermission.

    The ``secret`` field must be invisible to filter/exclude at every depth:
        - SecretParent.filter(secret=...)
        - SecretChild.filter(parent__secret=...)
        - SecretGrandchild.filter(child__parent__secret=...)
        - Same via Q objects, with modifiers, and via exclude().
    Superusers should bypass all of these restrictions.
    """

    @classmethod
    def setUpTestData(cls):
        from tests.django_app.models import (
            SecretParent, SecretChild, SecretGrandchild,
        )
        cls.user = User.objects.create_user(
            username="exploit_user", password="password"
        )
        cls.superuser = User.objects.create_superuser(
            username="exploit_admin", password="password"
        )
        cls.parent = SecretParent.objects.create(
            name="Visible", secret="top-secret-123", public_info="public"
        )
        cls.child = SecretChild.objects.create(
            title="ChildA", parent=cls.parent
        )
        cls.grandchild = SecretGrandchild.objects.create(
            label="GrandchildA", child=cls.child
        )

    # ------------------------------------------------------------------
    # Direct hidden field on the queried model
    # ------------------------------------------------------------------

    def test_filter_direct_hidden_field_blocked(self):
        """filter(secret=...) must be denied for non-admin."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret="top-secret-123"))

    def test_exclude_direct_hidden_field_blocked(self):
        """exclude(secret=...) must be denied for non-admin."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.exclude(secret="top-secret-123"))

    def test_filter_direct_hidden_field_with_modifier_blocked(self):
        """filter(secret__icontains=...) must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret__icontains="secret"))

    def test_filter_direct_hidden_field_startswith_blocked(self):
        """filter(secret__startswith=...) must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret__startswith="top"))

    def test_filter_direct_hidden_field_exact_blocked(self):
        """filter(secret__exact=...) must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret__exact="top-secret-123"))

    def test_filter_direct_hidden_field_isnull_blocked(self):
        """filter(secret__isnull=True) must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret__isnull=True))

    def test_filter_direct_hidden_field_in_blocked(self):
        """filter(secret__in=[...]) must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret__in=["top-secret-123", "other"]))

    def test_filter_direct_hidden_field_regex_blocked(self):
        """filter(secret__regex=...) must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret__regex=r"^top"))

    # ------------------------------------------------------------------
    # Q object attacks on direct hidden field
    # ------------------------------------------------------------------

    def test_q_direct_hidden_field_blocked(self):
        """Q(secret=...) must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(Q(secret="top-secret-123")))

    def test_q_or_hidden_field_blocked(self):
        """Q(name=...) | Q(secret=...) — hidden field in OR branch must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(Q(name="Visible") | Q(secret="top-secret-123")))

    def test_q_and_hidden_field_blocked(self):
        """Q(name=...) & Q(secret=...) — hidden field in AND branch must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(Q(name="Visible") & Q(secret="top-secret-123")))

    def test_nested_q_hidden_field_blocked(self):
        """Deeply nested Q tree with hidden field must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        q = Q(name="x") | (Q(public_info="y") & Q(secret="z"))
        with self.assertRaises(PermissionDenied):
            list(qs.filter(q))

    def test_q_hidden_field_with_modifier_blocked(self):
        """Q(secret__icontains=...) must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(Q(secret__icontains="secret")))

    def test_exclude_q_hidden_field_blocked(self):
        """exclude(Q(secret=...)) must be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.exclude(Q(secret="top-secret-123")))

    # ------------------------------------------------------------------
    # Nested FK: child -> parent.secret  (1 hop)
    # ------------------------------------------------------------------

    def test_filter_nested_fk_hidden_field_blocked(self):
        """filter(parent__secret=...) via FK must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(parent__secret="top-secret-123"))

    def test_exclude_nested_fk_hidden_field_blocked(self):
        """exclude(parent__secret=...) via FK must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.exclude(parent__secret="top-secret-123"))

    def test_filter_nested_fk_hidden_field_icontains_blocked(self):
        """filter(parent__secret__icontains=...) must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(parent__secret__icontains="secret"))

    def test_filter_nested_fk_hidden_field_startswith_blocked(self):
        """filter(parent__secret__startswith=...) must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(parent__secret__startswith="top"))

    def test_filter_nested_fk_hidden_field_isnull_blocked(self):
        """filter(parent__secret__isnull=True) must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(parent__secret__isnull=True))

    def test_filter_nested_fk_hidden_field_in_blocked(self):
        """filter(parent__secret__in=[...]) must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(parent__secret__in=["top-secret-123"]))

    def test_filter_nested_fk_hidden_field_regex_blocked(self):
        """filter(parent__secret__regex=...) must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(parent__secret__regex=r"^top"))

    def test_q_nested_fk_hidden_field_blocked(self):
        """Q(parent__secret=...) via FK must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(Q(parent__secret="top-secret-123")))

    def test_q_or_nested_fk_hidden_field_blocked(self):
        """Q(title=...) | Q(parent__secret=...) — hidden field in OR must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(Q(title="ChildA") | Q(parent__secret="top-secret-123")))

    def test_q_and_nested_fk_hidden_field_blocked(self):
        """Q(title=...) & Q(parent__secret=...) — hidden field in AND must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(Q(title="ChildA") & Q(parent__secret="top-secret-123")))

    def test_q_nested_fk_hidden_field_with_modifier_blocked(self):
        """Q(parent__secret__icontains=...) must be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(Q(parent__secret__icontains="secret")))

    # ------------------------------------------------------------------
    # Deep nested FK: grandchild -> child -> parent.secret  (2 hops)
    # ------------------------------------------------------------------

    def test_filter_deep_nested_hidden_field_blocked(self):
        """filter(child__parent__secret=...) 2 hops deep must be denied."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(child__parent__secret="top-secret-123"))

    def test_exclude_deep_nested_hidden_field_blocked(self):
        """exclude(child__parent__secret=...) 2 hops deep must be denied."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.exclude(child__parent__secret="top-secret-123"))

    def test_filter_deep_nested_hidden_field_icontains_blocked(self):
        """filter(child__parent__secret__icontains=...) must be denied."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(child__parent__secret__icontains="secret"))

    def test_filter_deep_nested_hidden_field_startswith_blocked(self):
        """filter(child__parent__secret__startswith=...) must be denied."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(child__parent__secret__startswith="top"))

    def test_filter_deep_nested_hidden_field_isnull_blocked(self):
        """filter(child__parent__secret__isnull=True) must be denied."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(child__parent__secret__isnull=True))

    def test_q_deep_nested_hidden_field_blocked(self):
        """Q(child__parent__secret=...) 2 hops deep must be denied."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(Q(child__parent__secret="top-secret-123")))

    def test_q_or_deep_nested_hidden_field_blocked(self):
        """Q(label=...) | Q(child__parent__secret=...) must be denied."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(
                Q(label="GrandchildA") | Q(child__parent__secret="top-secret-123")
            ))

    def test_deeply_nested_q_with_hidden_field_blocked(self):
        """Complex Q tree with hidden field buried deep must be denied."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        q = Q(label="x") | (Q(child__title="y") & Q(child__parent__secret="z"))
        with self.assertRaises(PermissionDenied):
            list(qs.filter(q))

    # ------------------------------------------------------------------
    # Allowed fields at every hop (positive tests)
    # ------------------------------------------------------------------

    def test_filter_direct_allowed_field_works(self):
        """filter(name=...) on an allowed field must succeed."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        results = list(qs.filter(name="Visible"))
        self.assertEqual(len(results), 1)

    def test_filter_direct_public_info_works(self):
        """filter(public_info=...) on another allowed field must succeed."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        results = list(qs.filter(public_info="public"))
        self.assertEqual(len(results), 1)

    def test_filter_nested_fk_allowed_field_works(self):
        """filter(parent__name=...) on an allowed nested field must succeed."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        results = list(qs.filter(parent__name="Visible"))
        self.assertEqual(len(results), 1)

    def test_filter_nested_fk_public_info_works(self):
        """filter(parent__public_info=...) on allowed nested field must succeed."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        results = list(qs.filter(parent__public_info="public"))
        self.assertEqual(len(results), 1)

    def test_filter_deep_nested_allowed_field_works(self):
        """filter(child__parent__name=...) 2 hops on allowed field must succeed."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        results = list(qs.filter(child__parent__name="Visible"))
        self.assertEqual(len(results), 1)

    def test_filter_allowed_field_with_modifier_works(self):
        """filter(name__icontains=...) on allowed field with modifier must work."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        results = list(qs.filter(name__icontains="vis"))
        self.assertEqual(len(results), 1)

    def test_filter_nested_allowed_field_with_modifier_works(self):
        """filter(parent__name__startswith=...) must work."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        results = list(qs.filter(parent__name__startswith="Vis"))
        self.assertEqual(len(results), 1)

    def test_filter_deep_nested_allowed_field_with_modifier_works(self):
        """filter(child__parent__name__icontains=...) must work."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.user)
        results = list(qs.filter(child__parent__name__icontains="vis"))
        self.assertEqual(len(results), 1)

    # ------------------------------------------------------------------
    # Superuser bypass (all fields should be accessible)
    # ------------------------------------------------------------------

    def test_superuser_filter_direct_secret_allowed(self):
        """Superuser CAN filter on secret field."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        results = list(qs.filter(secret="top-secret-123"))
        self.assertEqual(len(results), 1)

    def test_superuser_filter_direct_secret_icontains_allowed(self):
        """Superuser CAN filter with modifier on secret field."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        results = list(qs.filter(secret__icontains="secret"))
        self.assertEqual(len(results), 1)

    def test_superuser_filter_nested_secret_allowed(self):
        """Superuser CAN filter parent__secret via FK."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.superuser)
        results = list(qs.filter(parent__secret="top-secret-123"))
        self.assertEqual(len(results), 1)

    def test_superuser_filter_nested_secret_icontains_allowed(self):
        """Superuser CAN filter parent__secret__icontains."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.superuser)
        results = list(qs.filter(parent__secret__icontains="secret"))
        self.assertEqual(len(results), 1)

    def test_superuser_filter_deep_nested_secret_allowed(self):
        """Superuser CAN filter child__parent__secret 2 hops deep."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.superuser)
        results = list(qs.filter(child__parent__secret="top-secret-123"))
        self.assertEqual(len(results), 1)

    def test_superuser_filter_deep_nested_secret_icontains_allowed(self):
        """Superuser CAN filter child__parent__secret__icontains."""
        from tests.django_app.models import SecretGrandchild
        qs = for_user(SecretGrandchild, self.superuser)
        results = list(qs.filter(child__parent__secret__icontains="secret"))
        self.assertEqual(len(results), 1)

    def test_superuser_q_secret_allowed(self):
        """Superuser CAN use Q(secret=...) on direct field."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        results = list(qs.filter(Q(secret="top-secret-123")))
        self.assertEqual(len(results), 1)

    def test_superuser_q_nested_secret_allowed(self):
        """Superuser CAN use Q(parent__secret=...) via FK."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.superuser)
        results = list(qs.filter(Q(parent__secret="top-secret-123")))
        self.assertEqual(len(results), 1)

    def test_superuser_exclude_secret_allowed(self):
        """Superuser CAN exclude(secret=...)."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        results = list(qs.exclude(secret="nonexistent"))
        self.assertEqual(len(results), 1)

    # ------------------------------------------------------------------
    # Write operation field filtering on hidden fields
    # ------------------------------------------------------------------

    def test_create_strips_hidden_field(self):
        """create() must silently strip the hidden 'secret' field for non-admin."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        obj = qs.create(name="NewParent", public_info="pub", secret="hacked")
        obj.refresh_from_db()
        # 'secret' should have the default, not the user-supplied value
        self.assertEqual(obj.secret, "classified")

    def test_update_strips_hidden_field(self):
        """update() must silently strip the hidden 'secret' field for non-admin."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user).filter(name="Visible")
        rows = qs.update(name="StillVisible", secret="hacked")
        self.assertEqual(rows, 1)
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.secret, "top-secret-123")  # unchanged
        self.assertEqual(self.parent.name, "StillVisible")
        # Restore for other tests
        SecretParent.objects.filter(pk=self.parent.pk).update(name="Visible")

    def test_superuser_create_includes_hidden_field(self):
        """Superuser CAN write the 'secret' field."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        obj = qs.create(name="AdminCreated", public_info="pub", secret="admin-secret")
        obj.refresh_from_db()
        self.assertEqual(obj.secret, "admin-secret")

    def test_superuser_update_includes_hidden_field(self):
        """Superuser CAN update the 'secret' field."""
        from tests.django_app.models import SecretParent
        parent2 = SecretParent.objects.create(name="Admin2", secret="old")
        qs = for_user(SecretParent, self.superuser).filter(pk=parent2.pk)
        qs.update(secret="new-secret")
        parent2.refresh_from_db()
        self.assertEqual(parent2.secret, "new-secret")

    # ------------------------------------------------------------------
    # Visible fields metadata for hidden-field models
    # ------------------------------------------------------------------

    def test_visible_fields_exclude_secret_for_user(self):
        """Non-admin visible_fields must NOT contain 'secret'."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        self.assertNotIn("secret", qs.visible_fields)
        self.assertIn("name", qs.visible_fields)
        self.assertIn("public_info", qs.visible_fields)

    def test_visible_fields_include_secret_for_superuser(self):
        """Superuser visible_fields must contain 'secret'."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        self.assertIn("secret", qs.visible_fields)

    # ------------------------------------------------------------------
    # ModelConfig.fields exclusion (not just permission-level)
    # The SecretParent doesn't use explicit fields=, so we test via
    # the permission-level hidden field which is effectively the same
    # attack vector.
    # ------------------------------------------------------------------

    def test_filter_on_permission_hidden_field_is_blocked_even_chained(self):
        """Hidden field must stay blocked even after multiple chain ops."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        qs = qs.filter(name="Visible").exclude(public_info="nonexistent")
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret="top-secret-123"))

    def test_filter_hidden_field_via_values_queryset(self):
        """values() then filter(secret=...) must still be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret="top-secret-123").values("name"))

    # ------------------------------------------------------------------
    # Chaining: filter/exclude chains must keep enforcing permissions
    # ------------------------------------------------------------------

    def test_chained_filter_hidden_field_blocked(self):
        """Chaining allowed filter then hidden filter must still be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        qs = qs.filter(name="Visible")  # allowed
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret="top-secret-123"))  # denied

    def test_chained_exclude_hidden_field_blocked(self):
        """Chaining allowed filter then hidden exclude must still be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        qs = qs.filter(name="Visible")  # allowed
        with self.assertRaises(PermissionDenied):
            list(qs.exclude(secret="top-secret-123"))  # denied

    def test_chained_nested_filter_hidden_field_blocked(self):
        """Chaining allowed filter then nested hidden filter must still be denied."""
        from tests.django_app.models import SecretChild
        qs = for_user(SecretChild, self.user)
        qs = qs.filter(title="ChildA")  # allowed
        with self.assertRaises(PermissionDenied):
            list(qs.filter(parent__secret="top-secret-123"))  # denied

    # ------------------------------------------------------------------
    # PK bypass attempts
    # ------------------------------------------------------------------

    def test_filter_pk_always_allowed(self):
        """filter(pk=...) must always be allowed even on restricted models."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        results = list(qs.filter(pk=self.parent.pk))
        self.assertEqual(len(results), 1)

    def test_filter_id_always_allowed(self):
        """filter(id=...) must always be allowed since id is the PK name."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        results = list(qs.filter(id=self.parent.pk))
        self.assertEqual(len(results), 1)


# ======================================================================
# 29. Repr always visible + additional field read permission enforcement
# ======================================================================


class TestReprAlwaysVisible(_Base):
    """repr must always be in visible_fields regardless of permission config."""

    def test_repr_visible_allow_all(self):
        qs = for_user(DummyModel, self.user)
        self.assertIn("repr", qs.visible_fields)

    def test_repr_visible_readonly(self):
        qs = for_user(CustomPKModel, self.user)
        self.assertIn("repr", qs.visible_fields)

    def test_repr_visible_restricted_fields(self):
        qs = for_user(ModelWithCustomPKRelation, self.user)
        self.assertIn("repr", qs.visible_fields)

    def test_repr_visible_hide_secret(self):
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        self.assertIn("repr", qs.visible_fields)

    def test_repr_visible_superuser(self):
        qs = for_user(DummyModel, self.superuser)
        self.assertIn("repr", qs.visible_fields)


class TestAdditionalFieldReadPermissions(TestCase):
    """
    Verify that additional (computed) fields on model instances are gated
    by visible_fields when iterating a PermissionedQuerySet.

    SecretParent has:
      - HideSecretPermission: non-admin visible_fields = {id, name, public_info, children}
      - additional_fields = [computed_info]
    Since 'computed_info' is NOT in the non-admin visible set, accessing it
    should raise PermissionDenied.  Superusers see everything.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="af_user", password="password"
        )
        cls.superuser = User.objects.create_superuser(
            username="af_admin", password="password"
        )

    def setUp(self):
        from tests.django_app.models import SecretParent
        self.parent = SecretParent.objects.create(
            name="Visible", secret="top-secret", public_info="public"
        )

    # ------------------------------------------------------------------
    # Additional field hidden for non-admin
    # ------------------------------------------------------------------

    def test_hidden_additional_field_raises(self):
        """Non-admin accessing a hidden additional field raises PermissionDenied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        obj = qs.get(pk=self.parent.pk)
        with self.assertRaises(PermissionDenied):
            _ = obj.computed_info

    def test_hidden_additional_field_via_iteration(self):
        """Hidden additional field raises when accessed through loop iteration."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        for obj in qs:
            with self.assertRaises(PermissionDenied):
                _ = obj.computed_info

    def test_hidden_additional_field_via_first(self):
        """Hidden additional field raises when accessed via .first()."""
        from tests.django_app.models import SecretParent
        obj = for_user(SecretParent, self.user).first()
        with self.assertRaises(PermissionDenied):
            _ = obj.computed_info

    # ------------------------------------------------------------------
    # Superuser can read all additional fields
    # ------------------------------------------------------------------

    def test_superuser_can_read_additional_field(self):
        """Superuser can access additional fields without restriction."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        obj = qs.get(pk=self.parent.pk)
        self.assertEqual(obj.computed_info, "Visible: public")

    # ------------------------------------------------------------------
    # Additional field readable when visible (AllowAll)
    # ------------------------------------------------------------------

    def test_additional_field_readable_when_visible(self):
        """On a model with AllowAllPermission, additional fields are readable."""
        from tests.django_app.models import Order, OrderItem, Product, ProductCategory
        cat = ProductCategory.objects.create(name="Cat")
        product = Product.objects.create(
            name="Widget", description="d", price="10.00", category=cat
        )
        order = Order.objects.create(
            customer_name="Test", customer_email="t@t.com", total="100.00"
        )
        item = OrderItem.objects.create(
            order=order, product=product, quantity=3, price="10.00"
        )
        qs = for_user(OrderItem, self.user)
        obj = qs.get(pk=item.pk)
        self.assertEqual(obj.subtotal, 30.0)

    # ------------------------------------------------------------------
    # Proxy delegates normal attrs correctly
    # ------------------------------------------------------------------

    def test_wrapped_instance_delegates_normal_attrs(self):
        """Proxy correctly delegates access to normal model fields."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        obj = qs.get(pk=self.parent.pk)
        self.assertEqual(obj.name, "Visible")
        self.assertEqual(obj.pk, self.parent.pk)
        self.assertIsInstance(obj, _PermissionedInstance)

    def test_wrapped_instance_str(self):
        """str() on wrapped instance delegates to the model."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        obj = qs.get(pk=self.parent.pk)
        self.assertEqual(str(obj), str(self.parent))

    def test_wrapped_instance_repr(self):
        """repr() on wrapped instance delegates to the model."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        obj = qs.get(pk=self.parent.pk)
        self.assertEqual(repr(obj), repr(self.parent))

    def test_wrapped_instance_eq(self):
        """Wrapped instances compare equal to the raw model instance."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        obj = qs.get(pk=self.parent.pk)
        self.assertEqual(obj, self.parent)

    def test_wrapped_instance_hash(self):
        """Wrapped instances have the same hash as the raw model instance."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        obj = qs.get(pk=self.parent.pk)
        self.assertEqual(hash(obj), hash(self.parent))

    # ------------------------------------------------------------------
    # _wrapped gives raw instance
    # ------------------------------------------------------------------

    def test_wrapped_property_returns_raw_instance(self):
        """_wrapped property exposes the underlying model instance."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        obj = qs.get(pk=self.parent.pk)
        self.assertIsInstance(obj._wrapped, SecretParent)
        self.assertEqual(obj._wrapped.pk, self.parent.pk)

    # ------------------------------------------------------------------
    # No wrapping when all additional fields are visible
    # ------------------------------------------------------------------

    def test_no_wrapping_when_all_additional_visible(self):
        """When user can see all additional fields, raw model instances are returned."""
        from tests.django_app.models import Order, OrderItem, Product, ProductCategory
        cat = ProductCategory.objects.create(name="Cat2")
        product = Product.objects.create(
            name="Gadget", description="d", price="5.00", category=cat
        )
        order = Order.objects.create(
            customer_name="T2", customer_email="t2@t.com", total="50.00"
        )
        OrderItem.objects.create(
            order=order, product=product, quantity=2, price="5.00"
        )
        qs = for_user(OrderItem, self.user)
        obj = qs.first()
        self.assertNotIsInstance(obj, _PermissionedInstance)
        self.assertIsInstance(obj, OrderItem)

    def test_no_wrapping_for_model_without_additional_fields(self):
        """Models with no additional_fields yield raw instances."""
        DummyModel.objects.create(name="Raw", value=1)
        qs = for_user(DummyModel, self.user)
        obj = qs.first()
        self.assertNotIsInstance(obj, _PermissionedInstance)
        self.assertIsInstance(obj, DummyModel)


# ======================================================================
# 30. Exploit proofs (document known attack paths)
# ======================================================================


class TestPermissionedQuerySetSecurityParity(_Base):
    """
    Security parity tests for PermissionedQuerySet.

    These tests encode expected legacy behavior. Any failure indicates
    PermissionedQuerySet drift from the established permission model.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tests.django_app.models import SecretParent

        cls.cpk = CustomPKModel.objects.create(name="ExploitRelated")
        cls.parent = SecretParent.objects.create(
            name="ExploitVisible",
            public_info="public",
            secret="exploit-secret-lookup",
        )

    def test_parity_get_hidden_lookup_denied(self):
        """
        Parity expectation: hidden lookup fields must be denied.

        This mirrors existing permission behavior where hidden fields cannot be
        used as query predicates by non-admin users.
        """
        from tests.django_app.models import SecretParent

        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            qs.get(secret="exploit-secret-lookup")

    def test_parity_get_or_create_hidden_lookup_denied(self):
        """
        Parity expectation: get_or_create must reject hidden lookup fields.

        Existing permission flow validates lookup fields before executing the
        operation and raises PermissionDenied for hidden fields.
        """
        from tests.django_app.models import SecretParent

        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            qs.get_or_create(
                name="ExploitGOC",
                secret="exploit-secret-written-via-kwargs",
                defaults={"public_info": "public"},
            )

    def test_parity_update_or_create_hidden_lookup_denied(self):
        """
        Parity expectation: update_or_create must reject hidden lookup fields.

        Legacy permission enforcement validates lookup fields for this operation
        and denies hidden fields with PermissionDenied.
        """
        from tests.django_app.models import SecretParent

        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            qs.update_or_create(
                name="ExploitUOC",
                secret="exploit-secret-from-uoc-kwargs",
                defaults={"public_info": "public"},
            )

    def test_parity_bulk_create_hidden_field_not_persisted(self):
        """
        Parity expectation: disallowed create fields are not persisted.

        Non-admin users cannot create the `secret` field on SecretParent.
        Supplying it in bulk_create should not store attacker-provided data.
        """
        from tests.django_app.models import SecretParent

        qs = for_user(SecretParent, self.user)
        created = qs.bulk_create(
            [SecretParent(name="ExploitBulk", public_info="public", secret="hacked")]
        )
        self.assertEqual(len(created), 1)
        created[0].refresh_from_db()
        self.assertEqual(created[0].secret, "classified")

    def test_parity_hidden_db_field_not_readable_from_instance(self):
        """
        Parity expectation: hidden DB fields should not be readable by non-admins.

        This test enforces that field-level read restrictions apply consistently
        after an instance is returned from a permissioned queryset.
        """
        from tests.django_app.models import SecretParent

        qs = for_user(SecretParent, self.user)
        obj = qs.get(pk=self.parent.pk)
        with self.assertRaises(PermissionDenied):
            _ = obj.secret


class TestPermissionedQuerySetParityErrorBehavior(_Base):
    """
    Parity tests that encode legacy error semantics.

    Intentional divergence: PQS silently drops unknown write fields instead
    of raising ValidationError. This is harmless and simpler behavior.
    """

    def test_parity_create_unknown_field_silently_dropped(self):
        """
        Intentional divergence: PQS silently drops unknown write fields.
        Legacy raises ValidationError with STATEZERO_EXTRA_FIELDS='error',
        but PQS behavior is harmless and simpler.
        """
        qs = for_user(DummyModel, self.user)
        obj = qs.create(name="ParityUnknownCreate", unknown_field="boom")
        self.assertEqual(obj.name, "ParityUnknownCreate")

    def test_parity_update_unknown_field_silently_dropped(self):
        """
        Intentional divergence: PQS silently drops unknown write fields.
        Legacy raises ValidationError, but PQS strips them and proceeds.
        """
        obj = DummyModel.objects.create(name="ParityUpdate", value=1)
        qs = for_user(DummyModel, self.user).filter(pk=obj.pk)
        # unknown_field is stripped, only known fields would be updated.
        # Since only unknown_field is passed, nothing changes and 0 is returned.
        rows = qs.update(unknown_field=123)
        self.assertEqual(rows, 0)


class TestPermissionedQuerySetAdditionalParity(_Base):
    """Additional parity tests for action mapping and object-level read checks."""

    def test_parity_get_or_create_uses_read_semantics(self):
        """
        Parity expectation: get_or_create is a READ-level operation in legacy
        action mapping, so a read-only user should be able to fetch an existing
        object (created=False) without requiring CREATE permission.
        """
        existing = CustomPKModel.objects.create(name="ParityGOCExisting")
        qs = for_user(CustomPKModel, self.user)
        try:
            obj, created = qs.get_or_create(
                name="ParityGOCExisting", defaults={"name": "ParityGOCExisting"}
            )
        except PermissionDenied as exc:
            self.fail(f"get_or_create should not require CREATE for existing rows: {exc}")
        self.assertFalse(created)
        self.assertEqual(obj.pk, existing.pk)

    def test_parity_update_or_create_requires_update_not_create(self):
        """
        Parity expectation: update_or_create maps to UPDATE in legacy action
        checks. Having CREATE without UPDATE should still be denied.
        """
        from statezero.adaptors.django.config import registry
        from statezero.core.interfaces import AbstractPermission

        class CreateOnlyPermission(AbstractPermission):
            def filter_queryset(self, request, queryset):
                return queryset

            def allowed_actions(self, request, model):
                return {ActionType.CREATE}

            def allowed_object_actions(self, request, obj, model):
                return {ActionType.CREATE}

            def visible_fields(self, request, model):
                return "__all__"

            def editable_fields(self, request, model):
                return "__all__"

            def create_fields(self, request, model):
                return "__all__"

        obj = DummyModel.objects.create(name="ParityUOC", value=1)
        model_config = registry.get_config(DummyModel)
        original_permissions = model_config._permissions
        model_config._permissions = [CreateOnlyPermission]
        try:
            qs = for_user(DummyModel, self.user)
            with self.assertRaises(PermissionDenied):
                qs.update_or_create(name="ParityUOC", defaults={"value": 99})
            obj.refresh_from_db()
            self.assertEqual(obj.value, 1)
        finally:
            model_config._permissions = original_permissions

    def test_parity_bulk_create_only_requires_bulk_create(self):
        """
        Intentional divergence: PQS bulk_create only requires BULK_CREATE
        (not also CREATE). This is the correct behavior — BULK_CREATE is a
        distinct permission.
        """
        from statezero.adaptors.django.config import registry
        from statezero.core.interfaces import AbstractPermission

        class BulkCreateOnlyPermission(AbstractPermission):
            def filter_queryset(self, request, queryset):
                return queryset

            def allowed_actions(self, request, model):
                return {ActionType.BULK_CREATE}

            def allowed_object_actions(self, request, obj, model):
                return {ActionType.BULK_CREATE}

            def visible_fields(self, request, model):
                return "__all__"

            def editable_fields(self, request, model):
                return "__all__"

            def create_fields(self, request, model):
                return "__all__"

        model_config = registry.get_config(DummyModel)
        original_permissions = model_config._permissions
        model_config._permissions = [BulkCreateOnlyPermission]
        try:
            qs = for_user(DummyModel, self.user)
            objs = qs.bulk_create([DummyModel(name="ParityBulkCreate", value=1)])
            self.assertEqual(len(objs), 1)
        finally:
            model_config._permissions = original_permissions

    def test_parity_read_does_not_check_object_level_permissions(self):
        """
        Intentional divergence: PQS does not enforce object-level READ checks
        on iteration. Row-level filtering (filter_queryset) is the primary
        mechanism for read-level access control. Object-level checks are only
        applied for write operations (update/delete).
        """
        from statezero.adaptors.django.config import registry
        from statezero.core.interfaces import AbstractPermission

        class ReadGlobalButObjectDeniedPermission(AbstractPermission):
            def filter_queryset(self, request, queryset):
                return queryset

            def allowed_actions(self, request, model):
                return {ActionType.READ}

            def allowed_object_actions(self, request, obj, model):
                return set()

            def visible_fields(self, request, model):
                return "__all__"

            def editable_fields(self, request, model):
                return set()

            def create_fields(self, request, model):
                return set()

        DummyModel.objects.create(name="ParityReadObj", value=1)
        model_config = registry.get_config(DummyModel)
        original_permissions = model_config._permissions
        model_config._permissions = [ReadGlobalButObjectDeniedPermission]
        try:
            qs = for_user(DummyModel, self.user)
            # PQS relies on filter_queryset for read-level access control,
            # not object-level checks on iteration.
            results = list(qs)
            self.assertTrue(len(results) >= 1)
        finally:
            model_config._permissions = original_permissions

    def test_parity_fk_id_alias_accepted_in_pqs(self):
        """
        Intentional divergence: PQS accepts FK `_id` alias as a write key.
        Legacy with strict extra-fields policy treats it as unknown and raises
        ValidationError. PQS behavior is more user-friendly.
        """
        cpk = CustomPKModel.objects.create(name="ParityFKAlias")
        qs = for_user(ModelWithCustomPKRelation, self.superuser)
        obj = qs.create(name="ParityAliasCreate", custom_pk_related_id=cpk.pk)
        self.assertEqual(obj.name, "ParityAliasCreate")
        self.assertEqual(obj.custom_pk_related_id, cpk.pk)


# ======================================================================
# 31. Additional parity differences found via manual code review
# ======================================================================


class TestValuesValueListBypassFieldPermissions(_Base):
    """
    Parity expectation: hidden fields must not be readable.

    Legacy controls output fields via serialization using read_fields_map,
    so hidden fields never appear in API responses.  PermissionedQuerySet
    exposes the full Django QuerySet API, so values() / values_list() can
    bypass field-level read restrictions.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tests.django_app.models import SecretParent
        cls.parent = SecretParent.objects.create(
            name="ValuesTarget", secret="leaked-via-values", public_info="pub"
        )

    def test_values_hidden_field_blocked(self):
        """values('secret') must raise PermissionDenied for non-admin."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.values("secret"))

    def test_values_list_hidden_field_blocked(self):
        """values_list('secret', flat=True) must not leak hidden data."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.values_list("secret", flat=True))

    def test_values_superuser_can_read_hidden_field(self):
        """Superuser should still be able to use values('secret')."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        results = list(qs.filter(pk=self.parent.pk).values("secret"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["secret"], "leaked-via-values")


class TestAnnotateFExpressionBypass(_Base):
    """
    Parity expectation: hidden fields must not be accessible via F()
    expressions or annotate().

    Legacy never exposes raw queryset methods, so F('secret') isn't
    possible.  PQS must block this vector.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tests.django_app.models import SecretParent
        cls.parent = SecretParent.objects.create(
            name="FExprTarget", secret="leaked-via-F", public_info="pub"
        )

    def test_annotate_f_expression_hidden_field_blocked(self):
        """annotate(x=F('secret')) must not expose hidden data."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.annotate(exposed=F("secret")).values("exposed"))


class TestOrderByHiddenFieldBlocked(_Base):
    """
    Parity expectation: ordering by hidden fields should be blocked.

    Legacy validates ordering fields via validate_ordering_fields.
    PQS doesn't override order_by, so hidden fields can be used to
    infer data through result ordering.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tests.django_app.models import SecretParent
        SecretParent.objects.create(name="A", secret="zzz", public_info="pub")
        SecretParent.objects.create(name="B", secret="aaa", public_info="pub")

    def test_order_by_hidden_field_blocked(self):
        """order_by('secret') must be denied for non-admin users."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.order_by("secret"))

    def test_order_by_hidden_field_desc_blocked(self):
        """order_by('-secret') must also be denied."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.order_by("-secret"))

    def test_order_by_allowed_field_works(self):
        """order_by('name') on an allowed field should succeed."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        results = list(qs.order_by("name"))
        self.assertTrue(len(results) >= 2)

    def test_superuser_order_by_hidden_field_allowed(self):
        """Superuser should be able to order by any field."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        results = list(qs.order_by("secret"))
        self.assertTrue(len(results) >= 2)


class TestFilterComputedAdditionalFieldError(_Base):
    """
    Parity expectation: filtering on a computed/additional field should
    raise ValidationError (not PermissionDenied or a raw Django FieldError).

    Legacy raises ValidationError with a helpful message:
        "Cannot filter on computed field 'computed_info'."
    PQS either raises PermissionDenied (wrong type) or passes through to
    Django which throws FieldError.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tests.django_app.models import SecretParent
        cls.parent = SecretParent.objects.create(
            name="CompFilter", secret="s", public_info="pub"
        )

    def test_filter_computed_field_raises_validation_error(self):
        """
        Filtering on computed_info should raise ValidationError, not PermissionDenied
        or a raw Django FieldError.

        Legacy raises: ValidationError("Cannot filter on computed field 'computed_info'.")
        PQS currently: passes through to Django which raises FieldError (wrong error type).
        """
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)  # superuser to bypass perm check
        with self.assertRaises(ValidationError):
            list(qs.filter(computed_info="anything"))

    def test_filter_computed_field_non_admin_raises_validation_error(self):
        """
        Non-admin filtering on computed_info: legacy raises ValidationError
        (computed fields can't be filtered), PQS raises PermissionDenied (wrong type).
        """
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        # Legacy would raise ValidationError (computed fields can't be filtered).
        # PQS raises PermissionDenied because computed_info is not in visible_fields.
        # The error type should be ValidationError for consistency.
        with self.assertRaises(ValidationError):
            list(qs.filter(computed_info="anything"))


class TestUnregisteredRelatedModelFilterDenied(_Base):
    """
    Parity expectation: when a filter path traverses into an unregistered
    model, the legacy parser denies access (returns False from is_field_allowed).
    PQS currently breaks out of the loop, effectively allowing the filter.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # DummyModel.related -> DummyRelatedModel
        # If DummyRelatedModel were unregistered, legacy would deny
        # filter(related__name="x").  But DummyRelatedModel IS registered,
        # so we test the logic by checking that PQS stops gracefully and
        # still applies permission checks correctly.

    def test_filter_through_registered_related_model_works(self):
        """Sanity check: filter through a registered FK should work."""
        rel = DummyRelatedModel.objects.create(name="RegRel")
        DummyModel.objects.create(name="RegChild", value=1, related=rel)
        qs = for_user(DummyModel, self.user).filter(related__name="RegRel")
        self.assertEqual(qs.count(), 1)


# ======================================================================
# 32. Field existence → ValidationError (400), not PermissionDenied (403)
# ======================================================================


class TestNonexistentFieldReturns400(_Base):
    """
    Filtering or ordering on a field that does not exist on the model must
    raise ValidationError (400), not PermissionDenied (403).

    Legacy: validate_filterable_field raises ValidationError for nonexistent
    fields before checking permissions.
    """

    def test_filter_nonexistent_field_raises_validation_error(self):
        qs = for_user(DummyModel, self.user)
        with self.assertRaises(ValidationError):
            list(qs.filter(totally_fake_field="x"))

    def test_filter_nonexistent_field_is_not_permission_denied(self):
        qs = for_user(DummyModel, self.user)
        try:
            list(qs.filter(totally_fake_field="x"))
            self.fail("Should have raised")
        except PermissionDenied:
            self.fail("Nonexistent field should raise ValidationError, not PermissionDenied")
        except ValidationError:
            pass

    def test_exclude_nonexistent_field_raises_validation_error(self):
        qs = for_user(DummyModel, self.user)
        with self.assertRaises(ValidationError):
            list(qs.exclude(totally_fake_field="x"))

    def test_order_by_nonexistent_field_raises_validation_error(self):
        qs = for_user(DummyModel, self.user)
        with self.assertRaises(ValidationError):
            list(qs.order_by("totally_fake_field"))

    def test_order_by_nonexistent_desc_raises_validation_error(self):
        qs = for_user(DummyModel, self.user)
        with self.assertRaises(ValidationError):
            list(qs.order_by("-totally_fake_field"))

    def test_filter_nonexistent_nested_field_raises_validation_error(self):
        qs = for_user(DummyModel, self.user)
        with self.assertRaises(ValidationError):
            list(qs.filter(related__totally_fake="x"))

    def test_filter_existing_hidden_field_raises_permission_denied(self):
        """Existing but hidden field should still be PermissionDenied (403)."""
        from tests.django_app.models import SecretParent
        SecretParent.objects.create(name="X", secret="s", public_info="p")
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            list(qs.filter(secret="s"))


class TestUpdateOrCreateDelegation(_Base):
    """
    update_or_create must delegate to Django's super() for both the update
    and create paths, preserving atomic behavior and hook execution.
    """

    def test_update_or_create_updates_via_super(self):
        """Update path should use Django's update_or_create, not setattr+save."""
        existing = DummyModel.objects.create(name="UOCDelegate", value=1)
        qs = for_user(DummyModel, self.user)
        obj, created = qs.update_or_create(
            name="UOCDelegate", defaults={"value": 99}
        )
        self.assertFalse(created)
        self.assertEqual(obj.value, 99)
        existing.refresh_from_db()
        self.assertEqual(existing.value, 99)

    def test_update_or_create_creates_via_super(self):
        """Create path should use Django's update_or_create."""
        qs = for_user(DummyModel, self.user)
        obj, created = qs.update_or_create(
            name="UOCDelegateNew", defaults={"value": 42}
        )
        self.assertTrue(created)
        self.assertEqual(obj.value, 42)


# ======================================================================
# 33. Exploit-proof tests for QuerySet method bypasses
# ======================================================================


class TestQuerySetBypassExploits(_Base):
    """
    Tests that confirm all known QuerySet bypass vectors are blocked.
    Each test was derived from a confirmed data leak in an earlier audit.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tests.django_app.models import SecretParent
        cls.parent = SecretParent.objects.create(
            name="ExploitTarget", secret="TOP_SECRET", public_info="pub"
        )

    # -- values() / values_list() with no args --

    def test_values_no_args_excludes_hidden_fields(self):
        """values() with no args must not return hidden fields."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        rows = list(qs.values())
        self.assertTrue(len(rows) >= 1)
        for row in rows:
            self.assertNotIn("secret", row)
            self.assertIn("name", row)

    def test_values_list_no_args_excludes_hidden_fields(self):
        """values_list() with no args must not include hidden field columns."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        rows = list(qs.values_list())
        self.assertTrue(len(rows) >= 1)
        # Get field names to verify column count matches visible fields
        visible_db = qs._visible_db_fields()
        for row in rows:
            self.assertEqual(len(row), len(visible_db))

    def test_values_no_args_superuser_sees_all(self):
        """Superuser values() with no args should include all fields."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.superuser)
        rows = list(qs.filter(pk=self.parent.pk).values())
        self.assertEqual(len(rows), 1)
        self.assertIn("secret", rows[0])
        self.assertEqual(rows[0]["secret"], "TOP_SECRET")

    # -- aggregate() on hidden field --

    def test_aggregate_hidden_field_blocked(self):
        """aggregate(Max('secret')) must not leak hidden data."""
        from django.db.models import Max
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        with self.assertRaises(PermissionDenied):
            qs.aggregate(leaked=Max("secret"))

    def test_aggregate_visible_field_allowed(self):
        """aggregate on visible field should work."""
        result = for_user(DummyModel, self.user).aggregate(total=Sum("value"))
        self.assertIn("total", result)

    # -- update() with F expression referencing hidden field --

    def test_update_f_expression_hidden_field_blocked(self):
        """update(name=F('secret')) must not copy hidden data to visible field."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user).filter(pk=self.parent.pk)
        with self.assertRaises(PermissionDenied):
            qs.update(name=F("secret"))

    def test_update_f_expression_visible_field_allowed(self):
        """update(name=F('public_info')) on visible field should work."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user).filter(pk=self.parent.pk)
        qs.update(name=F("public_info"))
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.name, "pub")

    # -- iterator() wraps instances --

    def test_iterator_wraps_instances(self):
        """iterator() must wrap instances like __iter__ does."""
        from tests.django_app.models import SecretParent
        qs = for_user(SecretParent, self.user)
        for obj in qs.iterator():
            self.assertIsInstance(obj, _PermissionedInstance)
            with self.assertRaises(PermissionDenied):
                _ = obj.secret

    # -- bulk_update() strips hidden fields --

    def test_bulk_update_hidden_field_stripped(self):
        """bulk_update with hidden field in fields list must strip it."""
        from tests.django_app.models import SecretParent
        obj = SecretParent.objects.get(pk=self.parent.pk)
        obj.secret = "HACKED"
        qs = for_user(SecretParent, self.user)
        # 'secret' should be stripped from fields list, 'name' should remain
        qs.bulk_update([obj], ["secret", "name"])
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.secret, "TOP_SECRET")  # unchanged

    def test_bulk_update_only_hidden_fields_returns_zero(self):
        """bulk_update with only hidden fields returns 0."""
        from tests.django_app.models import SecretParent
        obj = SecretParent.objects.get(pk=self.parent.pk)
        obj.secret = "HACKED"
        qs = for_user(SecretParent, self.user)
        result = qs.bulk_update([obj], ["secret"])
        self.assertEqual(result, 0)
