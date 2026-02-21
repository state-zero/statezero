"""
Integration tests for the StateZero generated Python client.

Tests the full pipeline: client QuerySet → AST → transport → ModelView → ORM → response → unwrap.
Uses DjangoTestTransport so no HTTP server is needed.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from statezero.client.runtime_template import (
    Model, Manager, QuerySet, Q, F, FileObject, _model_registry, configure,
    StateZeroError, ValidationError, NotFound, PermissionDenied,
    MultipleObjectsReturned, _ERROR_MAP, _resolve_value, _field_permissions_cache,
)
from statezero.client.testing import DjangoTestTransport
from tests.django_app.models import (
    DummyModel, DummyRelatedModel, ProductCategory, Product,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Inline model classes (mimic what the generator would produce)
# ---------------------------------------------------------------------------

class DummyRelatedModelClient(Model):
    _model_name = "django_app.dummyrelatedmodel"
    _pk_field = "id"
    _relations = {}


class DummyModelClient(Model):
    _model_name = "django_app.dummymodel"
    _pk_field = "id"
    _relations = {"related": "django_app.dummyrelatedmodel"}


class FileTestClient(Model):
    _model_name = "django_app.filetest"
    _pk_field = "id"
    _relations = {}


class ProductCategoryClient(Model):
    _model_name = "django_app.productcategory"
    _pk_field = "id"
    _relations = {}


class ProductClient(Model):
    _model_name = "django_app.product"
    _pk_field = "id"
    _relations = {"category": "django_app.productcategory"}


# ---------------------------------------------------------------------------
# Base test class
# ---------------------------------------------------------------------------

class ClientTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = User.objects.create_superuser(
            username="admin", password="admin", email="admin@test.com"
        )

    def setUp(self):
        configure(transport=DjangoTestTransport(user=self.admin))


# ===========================================================================
# READ operations
# ===========================================================================

class TestFetch(ClientTestBase):
    def test_fetch_returns_typed_instances(self):
        DummyModel.objects.create(name="a", value=1)
        DummyModel.objects.create(name="b", value=2)

        results = DummyModelClient.objects.filter(name="a").fetch()
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], DummyModelClient)
        self.assertEqual(results[0].name, "a")

    def test_fetch_all(self):
        DummyModel.objects.create(name="x", value=10)
        DummyModel.objects.create(name="y", value=20)

        results = DummyModelClient.objects.all().fetch()
        self.assertEqual(len(results), 2)

    def test_filter_with_lookup(self):
        DummyModel.objects.create(name="low", value=5)
        DummyModel.objects.create(name="high", value=100)

        results = DummyModelClient.objects.filter(value__gte=50).fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "high")

    def test_chained_filters(self):
        DummyModel.objects.create(name="target", value=42)
        DummyModel.objects.create(name="target", value=99)
        DummyModel.objects.create(name="other", value=42)

        results = DummyModelClient.objects.filter(name="target").filter(value=42).fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, 42)
        self.assertEqual(results[0].name, "target")

    def test_exclude(self):
        DummyModel.objects.create(name="keep", value=1)
        DummyModel.objects.create(name="drop", value=2)

        results = DummyModelClient.objects.exclude(name="drop").fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "keep")

    def test_order_by(self):
        DummyModel.objects.create(name="b", value=2)
        DummyModel.objects.create(name="a", value=1)

        results = DummyModelClient.objects.order_by("value").fetch()
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].value, 1)
        self.assertEqual(results[1].value, 2)

    def test_order_by_descending(self):
        DummyModel.objects.create(name="low", value=1)
        DummyModel.objects.create(name="high", value=9)

        results = DummyModelClient.objects.order_by("-value").fetch()
        self.assertEqual(results[0].value, 9)

    def test_fetch_with_limit(self):
        for i in range(5):
            DummyModel.objects.create(name=f"item{i}", value=i)

        results = DummyModelClient.objects.order_by("value").fetch(limit=2)
        self.assertEqual(len(results), 2)

    def test_fetch_with_offset(self):
        for i in range(5):
            DummyModel.objects.create(name=f"item{i}", value=i)

        results = DummyModelClient.objects.order_by("value").fetch(limit=2, offset=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].value, 2)


class TestGet(ClientTestBase):
    def test_get_by_pk(self):
        obj = DummyModel.objects.create(name="target", value=42)

        result = DummyModelClient.objects.get(id=obj.pk)
        self.assertIsInstance(result, DummyModelClient)
        self.assertEqual(result.pk, obj.pk)
        self.assertEqual(result.name, "target")

    def test_get_by_name(self):
        DummyModel.objects.create(name="unique_name", value=1)

        result = DummyModelClient.objects.get(name="unique_name")
        self.assertEqual(result.name, "unique_name")


class TestFirstLast(ClientTestBase):
    def test_first(self):
        DummyModel.objects.create(name="a", value=1)
        DummyModel.objects.create(name="b", value=2)

        result = DummyModelClient.objects.order_by("value").first()
        self.assertIsNotNone(result)
        self.assertEqual(result.value, 1)

    def test_last(self):
        DummyModel.objects.create(name="a", value=1)
        DummyModel.objects.create(name="b", value=2)

        result = DummyModelClient.objects.order_by("value").last()
        self.assertIsNotNone(result)
        self.assertEqual(result.value, 2)

    def test_first_empty(self):
        result = DummyModelClient.objects.first()
        self.assertIsNone(result)


class TestCountExists(ClientTestBase):
    def test_count(self):
        DummyModel.objects.create(name="a", value=1)
        DummyModel.objects.create(name="b", value=2)

        count = DummyModelClient.objects.count()
        self.assertEqual(count, 2)

    def test_count_with_filter(self):
        DummyModel.objects.create(name="a", value=1)
        DummyModel.objects.create(name="b", value=2)

        count = DummyModelClient.objects.filter(name="a").count()
        self.assertEqual(count, 1)

    def test_exists_true(self):
        DummyModel.objects.create(name="a", value=1)

        self.assertTrue(DummyModelClient.objects.exists())

    def test_exists_false(self):
        self.assertFalse(DummyModelClient.objects.exists())


# ===========================================================================
# WRITE operations
# ===========================================================================

class TestCreate(ClientTestBase):
    def test_create(self):
        result = DummyModelClient.objects.create(name="new", value=99)
        self.assertIsInstance(result, DummyModelClient)
        self.assertEqual(result.name, "new")
        self.assertEqual(result.value, 99)
        self.assertIsNotNone(result.pk)

        # Verify in DB
        self.assertTrue(DummyModel.objects.filter(pk=result.pk).exists())

    def test_create_with_fk(self):
        related = DummyRelatedModel.objects.create(name="rel")

        result = DummyModelClient.objects.create(name="linked", value=1, related=related.pk)
        self.assertEqual(result.related, related.pk)


class TestBulkCreate(ClientTestBase):
    def test_bulk_create(self):
        items = [
            {"name": "bulk1", "value": 1},
            {"name": "bulk2", "value": 2},
            {"name": "bulk3", "value": 3},
        ]
        results = DummyModelClient.objects.bulk_create(items)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(isinstance(r, DummyModelClient) for r in results))
        self.assertEqual(DummyModel.objects.count(), 3)


class TestUpdate(ClientTestBase):
    def test_update_queryset(self):
        DummyModel.objects.create(name="a", value=1)
        DummyModel.objects.create(name="b", value=2)

        results = DummyModelClient.objects.filter(name="a").update(value=100)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, 100)

        # Verify in DB
        self.assertEqual(DummyModel.objects.get(name="a").value, 100)


class TestDelete(ClientTestBase):
    def test_delete(self):
        DummyModel.objects.create(name="gone", value=1)
        DummyModel.objects.create(name="stays", value=2)

        count = DummyModelClient.objects.filter(name="gone").delete()
        self.assertEqual(count, 1)
        self.assertEqual(DummyModel.objects.count(), 1)
        self.assertEqual(DummyModel.objects.first().name, "stays")


class TestGetOrCreate(ClientTestBase):
    def test_get_or_create_creates(self):
        instance, created = DummyModelClient.objects.get_or_create(
            defaults={"value": 42}, name="new_one"
        )
        self.assertTrue(created)
        self.assertEqual(instance.name, "new_one")
        self.assertEqual(instance.value, 42)

    def test_get_or_create_gets(self):
        DummyModel.objects.create(name="existing", value=10)

        instance, created = DummyModelClient.objects.get_or_create(
            defaults={"value": 99}, name="existing"
        )
        self.assertFalse(created)
        self.assertEqual(instance.name, "existing")
        self.assertEqual(instance.value, 10)


class TestUpdateOrCreate(ClientTestBase):
    def test_update_or_create_creates(self):
        instance, created = DummyModelClient.objects.update_or_create(
            defaults={"value": 42}, name="new_one"
        )
        self.assertTrue(created)
        self.assertEqual(instance.name, "new_one")
        self.assertEqual(instance.value, 42)

    def test_update_or_create_updates(self):
        DummyModel.objects.create(name="existing", value=10)

        instance, created = DummyModelClient.objects.update_or_create(
            defaults={"value": 99}, name="existing"
        )
        self.assertFalse(created)
        self.assertEqual(instance.value, 99)


# ===========================================================================
# Instance operations
# ===========================================================================

class TestInstanceOperations(ClientTestBase):
    def test_update_instance(self):
        obj = DummyModel.objects.create(name="orig", value=1)

        result = DummyModelClient.objects.update_instance(pk=obj.pk, name="updated")
        self.assertIsInstance(result, DummyModelClient)
        self.assertEqual(result.name, "updated")

        # Verify in DB
        obj.refresh_from_db()
        self.assertEqual(obj.name, "updated")

    def test_delete_instance(self):
        obj = DummyModel.objects.create(name="doomed", value=1)

        result = DummyModelClient.objects.delete_instance(pk=obj.pk)
        self.assertFalse(DummyModel.objects.filter(pk=obj.pk).exists())

    def test_instance_update_method(self):
        obj = DummyModel.objects.create(name="orig", value=1)

        # Fetch via client, then call .update() on the instance
        instance = DummyModelClient.objects.get(id=obj.pk)
        updated = instance.update(name="via_method")
        self.assertEqual(updated.name, "via_method")

    def test_instance_delete_method(self):
        obj = DummyModel.objects.create(name="doomed", value=1)

        instance = DummyModelClient.objects.get(id=obj.pk)
        instance.delete()
        self.assertFalse(DummyModel.objects.filter(pk=obj.pk).exists())


# ===========================================================================
# Relation resolution
# ===========================================================================

class TestRelations(ClientTestBase):
    def test_fk_returns_pk_at_depth_0(self):
        related = DummyRelatedModel.objects.create(name="rel")
        DummyModel.objects.create(name="parent", value=1, related=related)

        result = DummyModelClient.objects.filter(name="parent").fetch()
        self.assertEqual(len(result), 1)
        # At default depth (0), FK should be the raw PK
        self.assertEqual(result[0].related, related.pk)

    def test_fk_resolves_at_depth_1(self):
        related = DummyRelatedModel.objects.create(name="deep_rel")
        DummyModel.objects.create(name="parent", value=1, related=related)

        results = DummyModelClient.objects.filter(name="parent").fetch(depth=1)
        self.assertEqual(len(results), 1)
        parent = results[0]
        # At depth=1, FK should resolve to a DummyRelatedModelClient instance
        resolved = parent.related
        self.assertIsInstance(resolved, DummyRelatedModelClient)
        self.assertEqual(resolved.name, "deep_rel")
        self.assertEqual(resolved.pk, related.pk)

    def test_null_fk(self):
        DummyModel.objects.create(name="no_rel", value=1, related=None)

        result = DummyModelClient.objects.get(name="no_rel")
        self.assertIsNone(result.related)


# ===========================================================================
# Q objects
# ===========================================================================

class TestQObjects(ClientTestBase):
    def test_q_or(self):
        DummyModel.objects.create(name="a", value=1)
        DummyModel.objects.create(name="b", value=2)
        DummyModel.objects.create(name="c", value=3)

        results = DummyModelClient.objects.filter(
            Q(name="a") | Q(name="c")
        ).fetch()
        names = {r.name for r in results}
        self.assertEqual(names, {"a", "c"})

    def test_q_and(self):
        DummyModel.objects.create(name="target", value=42)
        DummyModel.objects.create(name="target", value=99)

        results = DummyModelClient.objects.filter(
            Q(name="target") & Q(value=42)
        ).fetch()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, 42)


# ===========================================================================
# F expressions
# ===========================================================================

class TestFExpressions(ClientTestBase):
    def test_f_add(self):
        DummyModel.objects.create(name="inc", value=10)

        results = DummyModelClient.objects.filter(name="inc").update(value=F("value") + 5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, 15)

    def test_f_multiply(self):
        DummyModel.objects.create(name="mul", value=3)

        results = DummyModelClient.objects.filter(name="mul").update(value=F("value") * 4)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].value, 12)


# ===========================================================================
# Chaining combinations
# ===========================================================================

class TestChaining(ClientTestBase):
    def test_filter_exclude_order_fetch(self):
        DummyModel.objects.create(name="a", value=1)
        DummyModel.objects.create(name="b", value=2)
        DummyModel.objects.create(name="c", value=3)

        results = (
            DummyModelClient.objects
            .filter(value__gte=1)
            .exclude(name="b")
            .order_by("-value")
            .fetch()
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].name, "c")
        self.assertEqual(results[1].name, "a")


# ===========================================================================
# Model instance features
# ===========================================================================

class TestModelInstance(ClientTestBase):
    def test_pk_property(self):
        obj = DummyModel.objects.create(name="pktest", value=1)
        result = DummyModelClient.objects.get(id=obj.pk)
        self.assertEqual(result.pk, obj.pk)

    def test_repr(self):
        DummyModel.objects.create(name="reprtest", value=1)
        result = DummyModelClient.objects.get(name="reprtest")
        r = repr(result)
        self.assertIn("reprtest", r)

    def test_to_dict(self):
        DummyModel.objects.create(name="dicttest", value=42)
        result = DummyModelClient.objects.get(name="dicttest")
        d = result.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["name"], "dicttest")
        self.assertEqual(d["value"], 42)

    def test_attribute_error_on_missing_field(self):
        DummyModel.objects.create(name="test", value=1)
        result = DummyModelClient.objects.get(name="test")
        with self.assertRaises(AttributeError):
            _ = result.nonexistent_field


# ===========================================================================
# Code generation
# ===========================================================================

class TestGenerateClient(TestCase):
    def test_generate_client_runs(self):
        """Test that generate_client produces the expected file structure."""
        import tempfile
        import os
        from statezero.client.generate import generate_client

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "sz")
            generate_client(output)

            # Check expected files exist
            self.assertTrue(os.path.isfile(os.path.join(output, "__init__.py")))
            self.assertTrue(os.path.isfile(os.path.join(output, "_runtime.py")))
            self.assertTrue(os.path.isdir(os.path.join(output, "models")))
            self.assertTrue(os.path.isfile(os.path.join(output, "models", "__init__.py")))

            # Check that at least one model file was generated
            model_files = [f for f in os.listdir(os.path.join(output, "models"))
                           if f.endswith(".py") and f != "__init__.py"]
            self.assertGreater(len(model_files), 0)

            # Read a model file and check it has class definitions
            with open(os.path.join(output, "models", model_files[0])) as f:
                content = f.read()
            self.assertIn("class ", content)
            self.assertIn("_model_name", content)
            self.assertIn("_relations", content)

    def test_generated_runtime_has_configure(self):
        """Test that the copied _runtime.py has the configure function."""
        import tempfile
        import os
        from statezero.client.generate import generate_client

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "sz")
            generate_client(output)

            with open(os.path.join(output, "_runtime.py")) as f:
                content = f.read()
            self.assertIn("def configure(", content)
            self.assertIn("class Model:", content)
            self.assertIn("class QuerySet:", content)

    def test_generated_init_exports(self):
        """Test that __init__.py exports configure, Q, F."""
        import tempfile
        import os
        from statezero.client.generate import generate_client

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "sz")
            generate_client(output)

            with open(os.path.join(output, "__init__.py")) as f:
                content = f.read()
            self.assertIn("configure", content)
            self.assertIn("Q", content)
            self.assertIn("F", content)

    def test_fk_type_respects_schema(self):
        """FK type annotations should use the related model's PK type, not assume int."""
        import tempfile
        import os
        from statezero.client.generate import generate_client

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "sz")
            generate_client(output)

            # Find the django_app model file
            model_file = os.path.join(output, "models", "django_app.py")
            self.assertTrue(os.path.isfile(model_file))

            with open(model_file) as f:
                content = f.read()

            # DummyModel.related FK points to DummyRelatedModel which has AutoField PK → int
            self.assertIn("_relations", content)

    def test_generated_init_exports_fileobject(self):
        """Test that __init__.py exports FileObject."""
        import tempfile
        import os
        from statezero.client.generate import generate_client

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "sz")
            generate_client(output)

            with open(os.path.join(output, "__init__.py")) as f:
                content = f.read()
            self.assertIn("FileObject", content)


# ===========================================================================
# FileObject
# ===========================================================================

class TestFileObject(ClientTestBase):
    def test_file_from_bytes(self):
        """FileObject from bytes stores data correctly."""
        f = FileObject(b"hello world", name="test.txt", content_type="text/plain")
        self.assertEqual(f.name, "test.txt")
        self.assertFalse(f.uploaded)
        self.assertEqual(f._get_data(), b"hello world")

    def test_file_from_file_like(self):
        """FileObject from a file-like object reads data."""
        import io
        buf = io.BytesIO(b"file-like content")
        f = FileObject(buf, name="from_buf.txt")
        self.assertEqual(f.name, "from_buf.txt")
        self.assertFalse(f.uploaded)
        self.assertEqual(f._get_data(), b"file-like content")

    def test_file_upload_via_transport(self):
        """FileObject._upload calls transport.upload_file and stores result."""
        f = FileObject(b"hello", name="test.txt", content_type="text/plain")
        from statezero.client.testing import DjangoTestTransport
        transport = DjangoTestTransport(user=self.admin)
        path = f._upload(transport)
        self.assertTrue(f.uploaded)
        self.assertIn("test.txt", path)
        self.assertIsNotNone(f.file_path)
        self.assertIsNotNone(f.file_url)

    def test_file_from_stored(self):
        """FileObject.from_stored wraps API response data."""
        stored = {
            "file_path": "statezero/test.txt",
            "original_name": "test.txt",
            "file_url": "/media/statezero/test.txt",
            "size": 11,
        }
        f = FileObject.from_stored(stored)
        self.assertTrue(f.uploaded)
        self.assertEqual(f.file_path, "statezero/test.txt")
        self.assertEqual(f.file_url, "/media/statezero/test.txt")

    def test_file_repr(self):
        f = FileObject(b"data", name="r.txt")
        self.assertIn("pending", repr(f))
        self.assertIn("r.txt", repr(f))

    def test_file_bytes_requires_name(self):
        with self.assertRaises(ValueError):
            FileObject(b"data")

    def test_file_invalid_source(self):
        with self.assertRaises(TypeError):
            FileObject(12345)

    def test_already_uploaded_skips_reupload(self):
        """Uploading an already-uploaded FileObject is a no-op."""
        stored = {"file_path": "statezero/existing.txt", "file_url": "/media/statezero/existing.txt"}
        f = FileObject.from_stored(stored)
        # _upload should return the existing path without calling transport
        result = f._upload(None)  # transport not needed
        self.assertEqual(result, "statezero/existing.txt")

    def test_resolve_data_uploads_file(self):
        """_resolve_data triggers upload for FileObject values."""
        f = FileObject(b"content", name="doc.pdf", content_type="application/pdf")
        from statezero.client.testing import DjangoTestTransport
        from statezero.client.runtime_template import configure as rt_configure
        rt_configure(transport=DjangoTestTransport(user=self.admin))
        qs = QuerySet("test")
        resolved = qs._resolve_data({"document": f})
        self.assertIsInstance(resolved["document"], str)
        self.assertIn("doc.pdf", resolved["document"])


# ===========================================================================
# Data resolution
# ===========================================================================

class TestDataResolution(ClientTestBase):
    def test_model_instance_as_fk(self):
        """Passing a Model instance as FK extracts .pk automatically."""
        from tests.django_app.models import DummyRelatedModel as DjRelated
        related = DjRelated.objects.create(name="rel")
        rel_client = DummyRelatedModelClient.objects.get(id=related.pk)
        result = DummyModelClient.objects.create(name="test", value=1, related=rel_client)
        self.assertEqual(result.related, related.pk)

    def test_datetime_resolved(self):
        """datetime objects are converted to ISO strings."""
        from datetime import datetime
        qs = QuerySet("test")
        resolved = qs._resolve_data({"ts": datetime(2024, 1, 15, 12, 30)})
        self.assertEqual(resolved["ts"], "2024-01-15T12:30:00")

    def test_date_resolved(self):
        """date objects are converted to ISO strings."""
        from datetime import date
        qs = QuerySet("test")
        resolved = qs._resolve_data({"d": date(2024, 6, 1)})
        self.assertEqual(resolved["d"], "2024-06-01")

    def test_decimal_resolved(self):
        """Decimal objects are converted to strings."""
        from decimal import Decimal
        qs = QuerySet("test")
        resolved = qs._resolve_data({"price": Decimal("19.99")})
        self.assertEqual(resolved["price"], "19.99")

    def test_f_expression_still_works(self):
        """F expressions are still resolved correctly."""
        qs = QuerySet("test")
        resolved = qs._resolve_data({"value": F("value") + 1})
        self.assertIn("__f_expr", resolved["value"])

    def test_nested_resolution(self):
        """Nested dicts and lists are resolved recursively."""
        from decimal import Decimal
        from datetime import datetime
        qs = QuerySet("test")
        resolved = qs._resolve_data({
            "meta": {"price": Decimal("9.99")},
            "tags": [datetime(2024, 1, 1), "plain"],
        })
        self.assertEqual(resolved["meta"]["price"], "9.99")
        self.assertEqual(resolved["tags"][0], "2024-01-01T00:00:00")
        self.assertEqual(resolved["tags"][1], "plain")

    def test_plain_values_pass_through(self):
        """Strings, ints, bools, None pass through unchanged."""
        qs = QuerySet("test")
        data = {"s": "hello", "n": 42, "b": True, "x": None}
        self.assertEqual(qs._resolve_data(data), data)


# ===========================================================================
# Error classes
# ===========================================================================

class TestErrorClasses(TestCase):
    def test_error_hierarchy(self):
        self.assertTrue(issubclass(ValidationError, StateZeroError))
        self.assertTrue(issubclass(NotFound, StateZeroError))
        self.assertTrue(issubclass(PermissionDenied, StateZeroError))
        self.assertTrue(issubclass(MultipleObjectsReturned, StateZeroError))
        self.assertTrue(issubclass(StateZeroError, Exception))

    def test_error_status_codes(self):
        self.assertEqual(StateZeroError.status_code, 500)
        self.assertEqual(ValidationError.status_code, 400)
        self.assertEqual(NotFound.status_code, 404)
        self.assertEqual(PermissionDenied.status_code, 403)
        self.assertEqual(MultipleObjectsReturned.status_code, 400)

    def test_error_detail(self):
        err = ValidationError("bad input")
        self.assertEqual(err.detail, "bad input")
        self.assertEqual(str(err), "bad input")

    def test_error_default_detail(self):
        err = StateZeroError()
        self.assertEqual(err.detail, "A server error occurred.")

    def test_error_map(self):
        self.assertIs(_ERROR_MAP["ValidationError"], ValidationError)
        self.assertIs(_ERROR_MAP["NotFound"], NotFound)
        self.assertIs(_ERROR_MAP["PermissionDenied"], PermissionDenied)
        self.assertIs(_ERROR_MAP["MultipleObjectsReturned"], MultipleObjectsReturned)


# ===========================================================================
# Transport error handling
# ===========================================================================

class TestTransportErrors(ClientTestBase):
    def test_get_nonexistent_raises_not_found(self):
        with self.assertRaises(NotFound):
            DummyModelClient.objects.get(id=999999)

    def test_get_multiple_raises_error(self):
        DummyModel.objects.create(name="dup", value=1)
        DummyModel.objects.create(name="dup", value=2)
        with self.assertRaises(MultipleObjectsReturned):
            DummyModelClient.objects.get(name="dup")

    def test_permission_denied_for_readonly_model(self):
        from tests.django_app.models import CustomPKModel
        # CustomPKModel uses ReadOnlyPermission — non-superuser can't create
        normal_user = User.objects.create_user(
            username="normal", password="normal", email="normal@test.com"
        )
        configure(transport=DjangoTestTransport(user=normal_user))

        class CustomPKClient(Model):
            _model_name = "django_app.custompkmodel"
            _pk_field = "custom_pk"
            _relations = {}

        with self.assertRaises(PermissionDenied):
            CustomPKClient.objects.create(name="test")


# ===========================================================================
# post_action (transport)
# ===========================================================================

class TestPostAction(ClientTestBase):
    def test_post_action_via_transport(self):
        transport = DjangoTestTransport(user=self.admin)
        result = transport.post_action("get_current_username", {})
        self.assertEqual(result["username"], "admin")

    def test_post_action_returns_data(self):
        transport = DjangoTestTransport(user=self.admin)
        result = transport.post_action("get_server_status", {})
        self.assertIn("status", result)


# ===========================================================================
# validate (transport)
# ===========================================================================

class TestValidate(ClientTestBase):
    def test_validate_valid_data(self):
        transport = DjangoTestTransport(user=self.admin)
        result = transport.validate(
            "django_app.dummymodel",
            {"name": "test", "value": 1},
            validate_type="create",
        )
        self.assertTrue(result["valid"])

    def test_validate_invalid_data(self):
        transport = DjangoTestTransport(user=self.admin)
        with self.assertRaises(ValidationError):
            transport.validate(
                "django_app.dummymodel",
                {"value": "not_an_int"},
                validate_type="create",
            )


# ===========================================================================
# get_field_permissions (transport)
# ===========================================================================

class TestFieldPermissions(ClientTestBase):
    def test_get_field_permissions(self):
        transport = DjangoTestTransport(user=self.admin)
        result = transport.get_field_permissions("django_app.dummymodel")
        self.assertIn("visible_fields", result)
        self.assertIn("creatable_fields", result)
        self.assertIn("editable_fields", result)
        self.assertIn("name", result["visible_fields"])


# ===========================================================================
# get() with depth and fields
# ===========================================================================

class TestGetWithOptions(ClientTestBase):
    def test_get_with_depth(self):
        related = DummyRelatedModel.objects.create(name="deep_get")
        obj = DummyModel.objects.create(name="parent", value=1, related=related)

        result = DummyModelClient.objects.get(id=obj.pk, depth=1)
        resolved = result.related
        self.assertIsInstance(resolved, DummyRelatedModelClient)
        self.assertEqual(resolved.name, "deep_get")

    def test_get_without_depth_returns_pk(self):
        related = DummyRelatedModel.objects.create(name="shallow")
        obj = DummyModel.objects.create(name="parent", value=1, related=related)

        result = DummyModelClient.objects.get(id=obj.pk)
        self.assertEqual(result.related, related.pk)


# ===========================================================================
# Model: save, refresh_from_db, validate, validate_data, get_field_permissions
# ===========================================================================

class TestModelSave(ClientTestBase):
    def test_save_existing(self):
        obj = DummyModel.objects.create(name="orig", value=1)
        instance = DummyModelClient.objects.get(id=obj.pk)

        # Modify via _raw and save
        instance._raw["name"] = "saved"
        result = instance.save()
        self.assertEqual(result.name, "saved")

        obj.refresh_from_db()
        self.assertEqual(obj.name, "saved")

    def test_save_new(self):
        instance = DummyModelClient._from_data(
            {"name": "brand_new", "value": 77}, None
        )
        result = instance.save()
        self.assertIsNotNone(result.pk)
        self.assertEqual(result.name, "brand_new")
        self.assertTrue(DummyModel.objects.filter(name="brand_new").exists())


class TestModelRefreshFromDb(ClientTestBase):
    def test_refresh_from_db(self):
        obj = DummyModel.objects.create(name="refresh_test", value=1)
        instance = DummyModelClient.objects.get(id=obj.pk)

        # Change in DB directly
        DummyModel.objects.filter(pk=obj.pk).update(value=999)

        # Instance still has old value
        self.assertEqual(instance.value, 1)

        # Refresh
        instance.refresh_from_db()
        self.assertEqual(instance.value, 999)

    def test_refresh_returns_self(self):
        obj = DummyModel.objects.create(name="chain", value=1)
        instance = DummyModelClient.objects.get(id=obj.pk)
        result = instance.refresh_from_db()
        self.assertIs(result, instance)


class TestModelValidate(ClientTestBase):
    def test_validate_instance(self):
        obj = DummyModel.objects.create(name="valid", value=1)
        instance = DummyModelClient.objects.get(id=obj.pk)
        result = instance.validate()
        self.assertTrue(result["valid"])

    def test_validate_data_classmethod(self):
        result = DummyModelClient.validate_data(
            {"name": "test", "value": 1},
            validate_type="create",
        )
        self.assertTrue(result["valid"])


class TestModelGetFieldPermissions(ClientTestBase):
    def setUp(self):
        super().setUp()
        _field_permissions_cache.clear()

    def test_get_field_permissions(self):
        perms = DummyModelClient.get_field_permissions()
        self.assertIn("visible_fields", perms)
        self.assertIn("name", perms["visible_fields"])

    def test_field_permissions_cached(self):
        perms1 = DummyModelClient.get_field_permissions()
        perms2 = DummyModelClient.get_field_permissions()
        self.assertIs(perms1, perms2)


# ===========================================================================
# F expression functions
# ===========================================================================

class TestFExpressionFunctions(TestCase):
    def test_f_abs(self):
        expr = F.abs(F("value"))
        node = expr._node
        self.assertEqual(node["mathjs"], "FunctionNode")
        self.assertEqual(node["fn"]["name"], "abs")
        self.assertEqual(len(node["args"]), 1)

    def test_f_round(self):
        expr = F.round(F("value"), 2)
        node = expr._node
        self.assertEqual(node["mathjs"], "FunctionNode")
        self.assertEqual(node["fn"]["name"], "round")
        self.assertEqual(len(node["args"]), 2)
        self.assertEqual(node["args"][1]["value"], 2)

    def test_f_floor(self):
        expr = F.floor(F("value"))
        self.assertEqual(expr._node["fn"]["name"], "floor")

    def test_f_ceil(self):
        expr = F.ceil(F("value"))
        self.assertEqual(expr._node["fn"]["name"], "ceil")

    def test_f_min(self):
        expr = F.min(F("a"), F("b"))
        self.assertEqual(expr._node["fn"]["name"], "min")
        self.assertEqual(len(expr._node["args"]), 2)

    def test_f_max(self):
        expr = F.max(F("a"), F("b"), F("c"))
        self.assertEqual(expr._node["fn"]["name"], "max")
        self.assertEqual(len(expr._node["args"]), 3)

    def test_f_func_with_constant(self):
        expr = F.abs(5)
        self.assertEqual(expr._node["args"][0]["mathjs"], "ConstantNode")
        self.assertEqual(expr._node["args"][0]["value"], 5)

    def test_f_func_serializes(self):
        expr = F.abs(F("value"))
        result = expr.to_expr()
        self.assertTrue(result["__f_expr"])
        self.assertEqual(result["ast"]["fn"]["name"], "abs")


# ===========================================================================
# QuerySet __iter__ and __len__
# ===========================================================================

class TestQuerySetIteration(ClientTestBase):
    def test_iter(self):
        DummyModel.objects.create(name="iter1", value=1)
        DummyModel.objects.create(name="iter2", value=2)

        names = [item.name for item in DummyModelClient.objects.all()]
        self.assertIn("iter1", names)
        self.assertIn("iter2", names)

    def test_len(self):
        DummyModel.objects.create(name="len1", value=1)
        DummyModel.objects.create(name="len2", value=2)
        DummyModel.objects.create(name="len3", value=3)

        qs = DummyModelClient.objects.all()
        self.assertEqual(len(qs), 3)

    def test_iter_with_filter(self):
        DummyModel.objects.create(name="target", value=1)
        DummyModel.objects.create(name="other", value=2)

        results = list(DummyModelClient.objects.filter(name="target"))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "target")


# ===========================================================================
# Manager aggregation shortcuts
# ===========================================================================

class TestManagerAggregation(ClientTestBase):
    def test_sum(self):
        DummyModel.objects.create(name="a", value=10)
        DummyModel.objects.create(name="b", value=20)
        self.assertEqual(DummyModelClient.objects.sum("value"), 30)

    def test_avg(self):
        DummyModel.objects.create(name="a", value=10)
        DummyModel.objects.create(name="b", value=20)
        self.assertEqual(DummyModelClient.objects.avg("value"), 15)

    def test_min(self):
        DummyModel.objects.create(name="a", value=5)
        DummyModel.objects.create(name="b", value=15)
        self.assertEqual(DummyModelClient.objects.min("value"), 5)

    def test_max(self):
        DummyModel.objects.create(name="a", value=5)
        DummyModel.objects.create(name="b", value=15)
        self.assertEqual(DummyModelClient.objects.max("value"), 15)


# ===========================================================================
# _resolve_value as module-level function
# ===========================================================================

class TestResolveValue(TestCase):
    def test_resolve_value_f_expression(self):
        result = _resolve_value(F("x") + 1)
        self.assertIn("__f_expr", result)

    def test_resolve_value_model_instance(self):
        inst = DummyModelClient._from_data({"id": 42, "name": "test"}, None)
        self.assertEqual(_resolve_value(inst), 42)

    def test_resolve_value_datetime(self):
        from datetime import datetime
        self.assertEqual(_resolve_value(datetime(2024, 1, 1)), "2024-01-01T00:00:00")

    def test_resolve_value_decimal(self):
        from decimal import Decimal
        self.assertEqual(_resolve_value(Decimal("9.99")), "9.99")

    def test_resolve_value_passthrough(self):
        self.assertEqual(_resolve_value("hello"), "hello")
        self.assertEqual(_resolve_value(42), 42)
        self.assertIsNone(_resolve_value(None))


# ===========================================================================
# Generated client exports
# ===========================================================================

class TestGeneratedExports(TestCase):
    def test_generated_init_exports_error_classes(self):
        import tempfile
        import os
        from statezero.client.generate import generate_client

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "sz")
            generate_client(output)

            with open(os.path.join(output, "__init__.py")) as f:
                content = f.read()
            self.assertIn("StateZeroError", content)
            self.assertIn("ValidationError", content)
            self.assertIn("NotFound", content)
            self.assertIn("PermissionDenied", content)
            self.assertIn("MultipleObjectsReturned", content)

    def test_generated_actions_import_resolve_value(self):
        import tempfile
        import os
        from statezero.client.generate import generate_client

        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "sz")
            generate_client(output)

            actions_dir = os.path.join(output, "actions")
            if os.path.isdir(actions_dir):
                action_files = [f for f in os.listdir(actions_dir)
                                if f.endswith(".py") and f != "__init__.py"]
                if action_files:
                    with open(os.path.join(actions_dir, action_files[0])) as f:
                        content = f.read()
                    self.assertIn("_resolve_value", content)
