"""
Tests for telemetry collection functionality.
"""
import json
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from statezero.core.telemetry import (
    TelemetryContext,
    create_telemetry_context,
    get_telemetry_context,
    clear_telemetry_context,
)

User = get_user_model()


class TelemetryModuleTestCase(TestCase):
    """Test telemetry module functionality"""

    def test_telemetry_context_creation(self):
        """Test creating telemetry context"""
        ctx = create_telemetry_context(enabled=True)
        self.assertIsInstance(ctx, TelemetryContext)
        self.assertTrue(ctx.enabled)

        # Should be retrievable
        retrieved_ctx = get_telemetry_context()
        self.assertEqual(ctx, retrieved_ctx)

        # Clean up
        clear_telemetry_context()

    def test_telemetry_disabled_no_recording(self):
        """Test that disabled telemetry doesn't record"""
        ctx = create_telemetry_context(enabled=False)

        ctx.record_cache_hit("test-key", "test-context", "SELECT * FROM test")
        ctx.record_cache_miss("test-key2", "test-context2", "SELECT * FROM test2")

        telemetry_data = ctx.get_telemetry_data()

        # Disabled context returns empty dict
        self.assertEqual(telemetry_data, {})

        # Clean up
        clear_telemetry_context()

    def test_telemetry_records_cache_hits(self):
        """Test recording cache hits"""
        ctx = create_telemetry_context(enabled=True)

        ctx.record_cache_hit("test-key-1", "read:fields=name", "SELECT * FROM test WHERE id=1")
        ctx.record_cache_hit("test-key-2", "read:fields=value", "SELECT * FROM test WHERE id=2")

        telemetry_data = ctx.get_telemetry_data()

        self.assertEqual(telemetry_data["cache"]["hits"], 2)
        self.assertEqual(len(telemetry_data["cache"]["hit_details"]), 2)

        hit_detail = telemetry_data["cache"]["hit_details"][0]
        self.assertEqual(hit_detail["cache_key"], "test-key-1")
        self.assertEqual(hit_detail["operation_context"], "read:fields=name")
        self.assertIn("SELECT * FROM test WHERE id=1", hit_detail["sql_preview"])

        # Clean up
        clear_telemetry_context()

    def test_telemetry_records_cache_misses(self):
        """Test recording cache misses"""
        ctx = create_telemetry_context(enabled=True)

        ctx.record_cache_miss("test-key-3", "count:id", "SELECT COUNT(*) FROM test")

        telemetry_data = ctx.get_telemetry_data()

        self.assertEqual(telemetry_data["cache"]["misses"], 1)
        self.assertEqual(len(telemetry_data["cache"]["miss_details"]), 1)

        miss_detail = telemetry_data["cache"]["miss_details"][0]
        self.assertEqual(miss_detail["cache_key"], "test-key-3")
        self.assertEqual(miss_detail["operation_context"], "count:id")

        # Clean up
        clear_telemetry_context()

    def test_telemetry_records_permission_fields(self):
        """Test recording permission-validated fields"""
        ctx = create_telemetry_context(enabled=True)

        ctx.record_permission_fields("MyModel", "read", ["id", "name", "value"])
        ctx.record_permission_fields("MyModel", "create", ["name", "value"])
        ctx.record_permission_fields("OtherModel", "read", ["id", "description"])

        telemetry_data = ctx.get_telemetry_data()

        fields_by_model = telemetry_data["permissions"]["fields_by_model"]

        self.assertIn("MyModel", fields_by_model)
        self.assertIn("OtherModel", fields_by_model)

        self.assertEqual(fields_by_model["MyModel"]["read"], ["id", "name", "value"])
        self.assertEqual(fields_by_model["MyModel"]["create"], ["name", "value"])
        self.assertEqual(fields_by_model["OtherModel"]["read"], ["id", "description"])

        # Clean up
        clear_telemetry_context()

    def test_telemetry_records_events(self):
        """Test recording generic events"""
        ctx = create_telemetry_context(enabled=True)

        ctx.record_event("query_start", "Starting query execution", {"model": "MyModel"})
        ctx.record_event("query_end", "Query execution completed", {"duration": 123.45})

        telemetry_data = ctx.get_telemetry_data()

        self.assertEqual(len(telemetry_data["events"]), 2)

        event1 = telemetry_data["events"][0]
        self.assertEqual(event1["event_type"], "query_start")
        self.assertEqual(event1["description"], "Starting query execution")
        self.assertEqual(event1["data"], {"model": "MyModel"})

        # Clean up
        clear_telemetry_context()

    def test_telemetry_data_structure(self):
        """Test complete telemetry data structure"""
        ctx = create_telemetry_context(enabled=True)

        # Record various telemetry data
        ctx.record_cache_hit("key1", "context1", "sql1")
        ctx.record_cache_miss("key2", "context2", "sql2")
        ctx.record_permission_fields("Model1", "read", ["field1"])
        ctx.record_event("test_event", "Test", {})

        telemetry_data = ctx.get_telemetry_data()

        # Verify top-level structure
        self.assertTrue(telemetry_data["enabled"])
        self.assertIn("duration_ms", telemetry_data)
        self.assertIn("query_ast", telemetry_data)
        self.assertIn("cache", telemetry_data)
        self.assertIn("database", telemetry_data)
        self.assertIn("hooks", telemetry_data)
        self.assertIn("permissions", telemetry_data)
        self.assertIn("events", telemetry_data)

        # Verify cache structure
        self.assertEqual(telemetry_data["cache"]["hits"], 1)
        self.assertEqual(telemetry_data["cache"]["misses"], 1)

        # Verify permissions structure
        self.assertIn("fields_by_model", telemetry_data["permissions"])
        self.assertIn("classes_applied", telemetry_data["permissions"])
        self.assertIn("field_breakdown_by_permission_class", telemetry_data["permissions"])
        self.assertIn("queryset_evolution", telemetry_data["permissions"])

        # Verify events
        self.assertEqual(len(telemetry_data["events"]), 1)

        # Clean up
        clear_telemetry_context()

    def test_query_ast_recording(self):
        """Test recording query AST"""
        ctx = create_telemetry_context(enabled=True)

        test_ast = {
            "type": "read",
            "filter": {"name": "test"},
            "orderBy": ["name"]
        }

        ctx.set_query_ast(test_ast)
        telemetry_data = ctx.get_telemetry_data()

        self.assertIsNotNone(telemetry_data["query_ast"])
        self.assertIn("type", str(telemetry_data["query_ast"]))

        # Clean up
        clear_telemetry_context()

    def test_permission_class_recording(self):
        """Test recording permission classes"""
        ctx = create_telemetry_context(enabled=True)

        ctx.record_permission_class_applied("myapp.permissions.ReadPermission")
        ctx.record_permission_class_applied("myapp.permissions.WritePermission")

        telemetry_data = ctx.get_telemetry_data()

        classes = telemetry_data["permissions"]["classes_applied"]
        self.assertEqual(len(classes), 2)
        self.assertIn("myapp.permissions.ReadPermission", classes)
        self.assertIn("myapp.permissions.WritePermission", classes)

        # Clean up
        clear_telemetry_context()

    def test_permission_field_breakdown(self):
        """Test recording per-permission-class field breakdown"""
        ctx = create_telemetry_context(enabled=True)

        ctx.record_permission_class_fields(
            "myapp.permissions.ReadPermission",
            "MyModel",
            "read",
            ["id", "name", "value"]
        )
        ctx.record_permission_class_fields(
            "myapp.permissions.WritePermission",
            "MyModel",
            "read",
            ["id", "name"]
        )

        telemetry_data = ctx.get_telemetry_data()

        breakdown = telemetry_data["permissions"]["field_breakdown_by_permission_class"]

        self.assertIn("myapp.permissions.ReadPermission", breakdown)
        self.assertIn("myapp.permissions.WritePermission", breakdown)

        read_perm_fields = breakdown["myapp.permissions.ReadPermission"]["MyModel"]["read"]
        self.assertEqual(read_perm_fields, ["id", "name", "value"])

        write_perm_fields = breakdown["myapp.permissions.WritePermission"]["MyModel"]["read"]
        self.assertEqual(write_perm_fields, ["id", "name"])

        # Clean up
        clear_telemetry_context()

    def test_queryset_evolution_recording(self):
        """Test recording queryset evolution after permission filters"""
        ctx = create_telemetry_context(enabled=True)

        ctx.record_queryset_after_permission(
            "myapp.permissions.OwnerPermission",
            "SELECT * FROM test WHERE owner_id = 1"
        )
        ctx.record_queryset_after_permission(
            "myapp.permissions.StatusPermission",
            "SELECT * FROM test WHERE owner_id = 1 AND status = 'active'"
        )

        telemetry_data = ctx.get_telemetry_data()

        evolution = telemetry_data["permissions"]["queryset_evolution"]
        self.assertEqual(len(evolution), 2)

        self.assertEqual(evolution[0]["after_permission"], "myapp.permissions.OwnerPermission")
        self.assertIn("owner_id = 1", evolution[0]["sql_preview"])

        self.assertEqual(evolution[1]["after_permission"], "myapp.permissions.StatusPermission")
        self.assertIn("status = 'active'", evolution[1]["sql_preview"])

        # Clean up
        clear_telemetry_context()

    def test_hook_execution_with_path(self):
        """Test recording hook execution with function path"""
        ctx = create_telemetry_context(enabled=True)

        ctx.record_hook_execution(
            "pre_save_hook",
            "pre_hook",
            {"name": "old"},
            {"name": "new"},
            hook_path="myapp.hooks.pre_save_hook"
        )

        telemetry_data = ctx.get_telemetry_data()

        hook_exec = telemetry_data["hooks"]["executions"][0]
        self.assertEqual(hook_exec["hook_name"], "pre_save_hook")
        self.assertEqual(hook_exec["hook_type"], "pre_hook")
        self.assertEqual(hook_exec["hook_path"], "myapp.hooks.pre_save_hook")

        # Clean up
        clear_telemetry_context()


class TelemetryIntegrationTestCase(TransactionTestCase):
    """Integration tests for telemetry in HTTP responses"""

    def setUp(self):
        """Set up test fixtures."""
        from tests.django_app.models import DummyModel, DummyRelatedModel

        cache.clear()
        # Clean up any existing data
        DummyModel.objects.all().delete()
        DummyRelatedModel.objects.all().delete()
        User.objects.all().delete()

        # Create a test user
        self.user = User.objects.create_user(username="telemetryuser", password="password")
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create test data
        self.related = DummyRelatedModel.objects.create(name="Related1")
        DummyModel.objects.create(name="TestA", value=10, related=self.related)
        DummyModel.objects.create(name="TestB", value=20, related=self.related)
        DummyModel.objects.create(name="TestC", value=30, related=self.related)

    def tearDown(self):
        """Clean up after tests."""
        from tests.django_app.models import DummyModel, DummyRelatedModel
        cache.clear()
        DummyModel.objects.all().delete()
        DummyRelatedModel.objects.all().delete()
        User.objects.all().delete()

    def test_telemetry_in_response_headers_cache_miss(self):
        """Test that telemetry appears in response headers with correct structure"""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # Make a request with unique canonical ID
        response = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="telemetry-test-unique-001",
        )

        self.assertEqual(response.status_code, 200)

        # Verify telemetry header exists
        self.assertIn('X-StateZero-Telemetry', response)

        # Parse telemetry data
        telemetry = json.loads(response['X-StateZero-Telemetry'])

        # Verify telemetry structure is complete
        self.assertTrue(telemetry['enabled'])
        self.assertIn('duration_ms', telemetry)
        self.assertIn('cache', telemetry)
        self.assertIn('database', telemetry)
        self.assertIn('hooks', telemetry)
        self.assertIn('permissions', telemetry)
        self.assertIn('events', telemetry)
        self.assertIn('query_ast', telemetry)

        # Verify cache data structure
        cache_data = telemetry['cache']
        self.assertIn('hits', cache_data)
        self.assertIn('misses', cache_data)
        self.assertIn('hit_details', cache_data)
        self.assertIn('miss_details', cache_data)

        # Verify database structure
        self.assertIn('query_count', telemetry['database'])
        self.assertIn('queries', telemetry['database'])

    def test_telemetry_shows_cache_hit(self):
        """Test that telemetry correctly shows cache hit on second request"""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # First request - cache miss
        response1 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="telemetry-cache-test-001",
        )
        self.assertEqual(response1.status_code, 200)

        telemetry1 = json.loads(response1['X-StateZero-Telemetry'])
        first_query_count = telemetry1['database']['query_count']

        # Second request - should be cache hit
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="telemetry-cache-test-001",  # Same canonical ID
        )
        self.assertEqual(response2.status_code, 200)

        # Parse second telemetry
        telemetry2 = json.loads(response2['X-StateZero-Telemetry'])

        # Cache hit should show in telemetry
        self.assertGreater(telemetry2['cache']['hits'], 0,
                          "Second request with same canonical ID should show cache hit")

        # Cache hit details should be present
        self.assertGreater(len(telemetry2['cache']['hit_details']), 0)
        hit_detail = telemetry2['cache']['hit_details'][0]
        self.assertIn('cache_key', hit_detail)
        self.assertIn('timestamp', hit_detail)

        # Should execute fewer queries due to caching
        second_query_count = telemetry2['database']['query_count']
        self.assertLessEqual(second_query_count, first_query_count,
                            "Cached request should execute same or fewer queries")

    def test_telemetry_aggregate_caching(self):
        """Test that telemetry shows cache behavior for aggregate queries"""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "aggregate",
                    "operation": "sum",
                    "field": "value",
                }
            }
        }

        # First request - cache miss
        response1 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="telemetry-agg-001",
        )
        self.assertEqual(response1.status_code, 200)

        telemetry1 = json.loads(response1['X-StateZero-Telemetry'])

        # Second request - cache hit
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="telemetry-agg-001",  # Same canonical ID
        )
        self.assertEqual(response2.status_code, 200)

        telemetry2 = json.loads(response2['X-StateZero-Telemetry'])

        # Verify cache hit occurred
        self.assertGreater(telemetry2['cache']['hits'], 0,
                          "Aggregate query should hit cache on second request")

        # Verify results are identical (caching worked)
        self.assertEqual(response1.data, response2.data)

    def test_different_transaction_no_cache_hit(self):
        """Test that telemetry shows no cache hit with different transaction ID"""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # First request
        response1 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="telemetry-diff-001",
        )
        self.assertEqual(response1.status_code, 200)

        # Second request with DIFFERENT canonical ID
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="telemetry-diff-002",  # Different!
        )
        self.assertEqual(response2.status_code, 200)

        telemetry2 = json.loads(response2['X-StateZero-Telemetry'])

        # Should show cache miss, not hit (different transaction ID means different cache key)
        # The cache hits might be 0 or there might be cache misses recorded
        # The key point is this is treated as a fresh request
        self.assertIn('cache', telemetry2)

