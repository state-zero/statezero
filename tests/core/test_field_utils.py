"""
Tests for field_utils module.
"""

from django.test import TestCase

from statezero.core.field_utils import (
    extract_fields_from_filter,
    merge_fields_with_filter_fields,
    strip_lookup_operator,
)


class StripLookupOperatorTests(TestCase):
    def test_simple_field(self):
        self.assertEqual(strip_lookup_operator("status"), "status")

    def test_with_in_operator(self):
        self.assertEqual(strip_lookup_operator("status__in"), "status")

    def test_with_icontains(self):
        self.assertEqual(strip_lookup_operator("name__icontains"), "name")

    def test_nested_field_with_operator(self):
        self.assertEqual(strip_lookup_operator("user__email__icontains"), "user__email")

    def test_with_gte(self):
        self.assertEqual(strip_lookup_operator("created_at__gte"), "created_at")


class ExtractFieldsFromFilterTests(TestCase):
    def test_empty_filter(self):
        self.assertEqual(extract_fields_from_filter({}), set())
        self.assertEqual(extract_fields_from_filter(None), set())

    def test_simple_filter(self):
        filter_node = {
            "type": "filter",
            "conditions": {"status": "active"}
        }
        self.assertEqual(extract_fields_from_filter(filter_node), {"status"})

    def test_filter_with_lookup(self):
        filter_node = {
            "type": "filter",
            "conditions": {"status__in": ["active", "pending"]}
        }
        self.assertEqual(extract_fields_from_filter(filter_node), {"status"})

    def test_filter_multiple_fields(self):
        filter_node = {
            "type": "filter",
            "conditions": {
                "status__in": ["active"],
                "name__icontains": "test",
                "archived": False
            }
        }
        self.assertEqual(extract_fields_from_filter(filter_node), {"status", "name", "archived"})

    def test_nested_and_filter(self):
        filter_node = {
            "type": "and",
            "children": [
                {"type": "filter", "conditions": {"status": "active"}},
                {"type": "filter", "conditions": {"archived": False}}
            ]
        }
        self.assertEqual(extract_fields_from_filter(filter_node), {"status", "archived"})


class MergeFieldsWithFilterFieldsTests(TestCase):
    def test_no_filter_fields(self):
        result = merge_fields_with_filter_fields(["id", "name"], set())
        self.assertEqual(result, ["id", "name"])

    def test_add_filter_fields(self):
        result = merge_fields_with_filter_fields(["id", "name"], {"status"})
        self.assertIn("id", result)
        self.assertIn("name", result)
        self.assertIn("status", result)

    def test_no_duplicates(self):
        result = merge_fields_with_filter_fields(["id", "name", "status"], {"status"})
        self.assertEqual(result.count("status"), 1)

    def test_empty_requested_fields(self):
        result = merge_fields_with_filter_fields([], {"status", "archived"})
        self.assertEqual(set(result), {"status", "archived"})
