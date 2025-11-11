"""
Tests for telemetry collection functionality.
"""
from django.test import TestCase

from statezero.core.telemetry import (
    TelemetryContext,
    create_telemetry_context,
    get_telemetry_context,
    clear_telemetry_context,
)


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

