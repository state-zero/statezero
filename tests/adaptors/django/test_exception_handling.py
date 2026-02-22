"""
Exception handling tests: verify that Django DB errors (IntegrityError,
ProtectedError, DataError) are mapped to proper HTTP status codes and
error types instead of bubbling up as 500s.

Uses dedicated Error* models with AllowAll permissions so that errors
come purely from database constraints.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, DataError
from django.db.models import ProtectedError, RestrictedError
from django.test import TestCase, override_settings

from statezero.adaptors.django.exception_handler import (
    map_exception,
    explicit_exception_handler,
)
from statezero.client.runtime_template import (
    Model, configure, _field_permissions_cache,
    ConflictError, ValidationError, StateZeroError,
)
from statezero.client.testing import DjangoTestTransport
from statezero.core.exceptions import (
    ConflictError as CoreConflictError,
    ValidationError as CoreValidationError,
)
from tests.django_app.models import (
    ErrorTestParent,
    ErrorTestProtectedChild,
    ErrorTestUniqueModel,
    ErrorTestOneToOneModel,
    ErrorTestCompoundUnique,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Generated client model stubs (from: python manage.py generate_client)
# ---------------------------------------------------------------------------

class ErrorTestParentClient(Model):
    _model_name = "django_app.errortestparent"
    _pk_field = "id"
    _relations = {}


class ErrorTestProtectedChildClient(Model):
    _model_name = "django_app.errortestprotectedchild"
    _pk_field = "id"
    _relations = {'parent': 'django_app.errortestparent'}


class ErrorTestUniqueModelClient(Model):
    _model_name = "django_app.errortestuniquemodel"
    _pk_field = "id"
    _relations = {}


class ErrorTestOneToOneModelClient(Model):
    _model_name = "django_app.errortestonetoonemodel"
    _pk_field = "id"
    _relations = {'parent': 'django_app.errortestparent'}


class ErrorTestCompoundUniqueClient(Model):
    _model_name = "django_app.errortestcompoundunique"
    _pk_field = "id"
    _relations = {}


# ===========================================================================
# Unit tests for map_exception
# ===========================================================================

class MapExceptionTest(TestCase):
    """Test that map_exception correctly maps Django DB exceptions."""

    def test_integrity_error_maps_to_conflict(self):
        exc = IntegrityError("UNIQUE constraint failed: table.field")
        mapped = map_exception(exc)
        self.assertIsInstance(mapped, CoreConflictError)
        self.assertEqual(mapped.status_code, 409)

    def test_integrity_error_strips_pg_detail(self):
        """PostgreSQL DETAIL line is stripped from safe_detail."""
        exc = IntegrityError(
            'duplicate key value violates unique constraint "tbl_field_key"\n'
            'DETAIL:  Key (field)=(secret_value) already exists.'
        )
        mapped = map_exception(exc)
        self.assertIsInstance(mapped, CoreConflictError)
        # safe_detail should NOT contain the DETAIL line
        self.assertNotIn("secret_value", mapped.safe_detail)
        self.assertIn("duplicate key", mapped.safe_detail)
        # full detail should still have it (for debug mode)
        self.assertIn("secret_value", str(mapped.detail))

    def test_integrity_error_sqlite_no_detail_line(self):
        """SQLite messages have no DETAIL: line, safe_detail is the full message."""
        exc = IntegrityError("UNIQUE constraint failed: table.field")
        mapped = map_exception(exc)
        self.assertEqual(mapped.safe_detail, "UNIQUE constraint failed: table.field")

    def test_protected_error_maps_to_conflict(self):
        exc = ProtectedError(
            "Cannot delete some instances",
            set(["<obj1>", "<obj2>"]),
        )
        mapped = map_exception(exc)
        self.assertIsInstance(mapped, CoreConflictError)
        self.assertEqual(mapped.status_code, 409)
        # safe_detail should NOT leak object details
        self.assertNotIn("obj1", mapped.safe_detail)
        self.assertIn("other objects depend on it", mapped.safe_detail)

    def test_data_error_maps_to_validation(self):
        exc = DataError("value too long for type character varying(50)")
        mapped = map_exception(exc)
        self.assertIsInstance(mapped, CoreValidationError)
        self.assertEqual(mapped.status_code, 400)


# ===========================================================================
# Unit tests for explicit_exception_handler production gating
# ===========================================================================

class ExceptionHandlerProductionGatingTest(TestCase):
    """Test that sensitive details are hidden in production (DEBUG=False)."""

    @override_settings(DEBUG=False)
    def test_integrity_error_uses_safe_detail_in_production(self):
        exc = IntegrityError(
            'duplicate key value violates unique constraint "tbl_key"\n'
            'DETAIL:  Key (field)=(secret) already exists.'
        )
        response = explicit_exception_handler(exc)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("secret", response.data["detail"])
        self.assertIn("duplicate key", response.data["detail"])

    @override_settings(DEBUG=True)
    def test_integrity_error_shows_full_detail_in_debug(self):
        exc = IntegrityError(
            'duplicate key value violates unique constraint "tbl_key"\n'
            'DETAIL:  Key (field)=(secret) already exists.'
        )
        response = explicit_exception_handler(exc)
        self.assertEqual(response.status_code, 409)
        self.assertIn("secret", str(response.data["detail"]))

    @override_settings(DEBUG=False)
    def test_protected_error_uses_safe_detail_in_production(self):
        exc = ProtectedError("Cannot delete", set(["<SensitiveObj>"]))
        response = explicit_exception_handler(exc)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("SensitiveObj", response.data["detail"])
        self.assertEqual(response.data["type"], "ConflictError")

    @override_settings(DEBUG=False)
    def test_data_error_shows_detail_in_production(self):
        """DataError maps to 400 which is NOT production-gated (detail always shown)."""
        exc = DataError("value too long for type character varying(50)")
        response = explicit_exception_handler(exc)
        self.assertEqual(response.status_code, 400)
        self.assertIn("value too long", str(response.data["detail"]))


# ===========================================================================
# Integration tests through the Python client
# ===========================================================================

class ErrorHandlingIntegrationBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = User.objects.create_superuser(
            username="err_admin", password="admin", email="err@test.com"
        )

    def setUp(self):
        configure(transport=DjangoTestTransport(user=self.admin))
        _field_permissions_cache.clear()


class TestUniqueConstraintErrors(ErrorHandlingIntegrationBase):
    """DRF serializer catches unique violations on create as ValidationError (400)."""

    def test_duplicate_unique_field_raises_validation_error(self):
        ErrorTestUniqueModelClient.objects.create(code="ABC", label="first")
        with self.assertRaises(ValidationError):
            ErrorTestUniqueModelClient.objects.create(code="ABC", label="second")

    def test_duplicate_one_to_one_raises_error(self):
        """OneToOne duplicate is caught — either by DRF (ValidationError) or DB (ConflictError)."""
        parent = ErrorTestParent.objects.create(name="parent")
        ErrorTestOneToOneModelClient.objects.create(parent=parent.pk, note="first")
        with self.assertRaises((ValidationError, ConflictError)):
            ErrorTestOneToOneModelClient.objects.create(parent=parent.pk, note="second")

    def test_compound_unique_violation_raises_validation_error(self):
        ErrorTestCompoundUniqueClient.objects.create(group="A", rank=1, label="first")
        with self.assertRaises(ValidationError):
            ErrorTestCompoundUniqueClient.objects.create(group="A", rank=1, label="second")

    def test_compound_unique_different_rank_succeeds(self):
        ErrorTestCompoundUniqueClient.objects.create(group="B", rank=1, label="first")
        result = ErrorTestCompoundUniqueClient.objects.create(group="B", rank=2, label="second")
        self.assertIsNotNone(result.pk)


class TestProtectedFKErrors(ErrorHandlingIntegrationBase):
    """Deleting a parent with PROTECT children raises ConflictError (409)."""

    def test_delete_protected_parent_raises_conflict(self):
        parent = ErrorTestParent.objects.create(name="protected_parent")
        ErrorTestProtectedChild.objects.create(name="child", parent=parent)
        with self.assertRaises(ConflictError):
            ErrorTestParentClient.objects.filter(id=parent.pk).delete()

    def test_delete_parent_without_children_succeeds(self):
        parent = ErrorTestParent.objects.create(name="lonely_parent")
        ErrorTestParentClient.objects.filter(id=parent.pk).delete()
        self.assertFalse(ErrorTestParent.objects.filter(pk=parent.pk).exists())
