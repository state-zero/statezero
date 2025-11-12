"""
Tests for query-level caching write path.

Note: Read path has been disabled in favor of push-based approach via Pusher.
These tests verify the write path (cache_query_result) and cache key generation.
"""
import hashlib
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, RequestFactory

from statezero.core.context_storage import current_canonical_id
from statezero.core.query_cache import (
    _get_cache_key,
    _get_sql_from_queryset,
    cache_query_result,
    generate_cache_key_for_subscription,
)


User = get_user_model()


class TestCacheKeyGeneration(TestCase):
    """Test cache key generation logic."""

    def test_cache_key_deterministic(self):
        """Test that cache keys are generated deterministically."""
        sql = "SELECT * FROM users WHERE id = %s"
        params = (1,)
        txn_id = "txn-123"

        key1 = _get_cache_key(sql, params, txn_id)
        key2 = _get_cache_key(sql, params, txn_id)

        # Same inputs should produce same key
        assert key1 == key2
        assert key1.startswith("statezero:query:")

    def test_cache_key_differs_by_transaction(self):
        """Test that different transaction IDs produce different cache keys."""
        sql = "SELECT * FROM users WHERE id = %s"
        params = (1,)

        key1 = _get_cache_key(sql, params, "txn-123")
        key2 = _get_cache_key(sql, params, "txn-456")

        # Different transaction IDs should produce different keys
        assert key1 != key2

    def test_cache_key_differs_by_sql(self):
        """Test that different SQL produces different cache keys."""
        params = (1,)
        txn_id = "txn-123"

        key1 = _get_cache_key("SELECT * FROM users WHERE id = %s", params, txn_id)
        key2 = _get_cache_key("SELECT * FROM posts WHERE id = %s", params, txn_id)

        # Different SQL should produce different keys
        assert key1 != key2

    def test_cache_key_differs_by_params(self):
        """Test that different params produce different cache keys."""
        sql = "SELECT * FROM users WHERE id = %s"
        txn_id = "txn-123"

        key1 = _get_cache_key(sql, (1,), txn_id)
        key2 = _get_cache_key(sql, (2,), txn_id)

        # Different params should produce different keys
        assert key1 != key2

    def test_permissions_encoded_in_sql(self):
        """
        Test that permission filtering is encoded in SQL itself.

        This demonstrates the core insight: different users with different
        permissions produce different SQL, which automatically creates
        different cache keys. No manual permission tracking needed.
        """
        txn_id = "txn-123"

        # User 1 sees all records (admin)
        sql_admin = "SELECT * FROM messages"
        key_admin = _get_cache_key(sql_admin, None, txn_id)

        # User 2 only sees their room (filtered by permission)
        sql_user = "SELECT * FROM messages WHERE room_id = %s"
        key_user = _get_cache_key(sql_user, (5,), txn_id)

        # Different SQL = different cache key = automatic permission safety
        assert key_admin != key_user


class TestSQLExtraction(TestCase):
    """Test SQL extraction from QuerySet."""

    def test_extract_sql_from_queryset(self):
        """Test that we can extract SQL from a real QuerySet."""
        # Create a queryset
        queryset = User.objects.filter(username="testuser")

        # Extract SQL
        sql_data = _get_sql_from_queryset(queryset)

        assert sql_data is not None
        sql, params = sql_data
        assert isinstance(sql, str)
        assert "SELECT" in sql.upper()
        assert "username" in sql.lower() or "%s" in sql

    def test_extract_sql_with_filters(self):
        """Test SQL extraction includes filter conditions."""
        queryset = User.objects.filter(username="testuser", is_active=True)

        sql_data = _get_sql_from_queryset(queryset)

        assert sql_data is not None
        sql, params = sql_data
        # SQL should contain filter conditions
        assert "WHERE" in sql.upper() or len(params) > 0


class TestCachingFunctions(TestCase):
    """Test the write path caching functions."""

    def setUp(self):
        """Set up test fixtures."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        current_canonical_id.set(None)

    def test_cache_result_no_canonical_id(self):
        """Test that cache_query_result handles no canonical_id gracefully."""
        queryset = User.objects.all()
        current_canonical_id.set(None)

        test_result = {"data": [], "metadata": {}}

        # Should not raise error, just skip caching
        cache_query_result(queryset, test_result)

    def test_cache_result_with_canonical_id(self):
        """Test that cache_query_result stores data when canonical_id is set."""
        user = User.objects.create_user(username="testuser", password="testpass")
        queryset = User.objects.filter(username="testuser")
        txn_id = "txn-test-001"
        current_canonical_id.set(txn_id)

        test_result = {
            "data": [{"id": user.id, "username": "testuser"}],
            "metadata": {"read": True},
        }

        # Should not raise error
        cache_query_result(queryset, test_result)

        # Verify data was written to cache (testing write path)
        sql_data = _get_sql_from_queryset(queryset)
        assert sql_data is not None
        sql, params = sql_data
        cache_key = _get_cache_key(sql, params, txn_id, None)
        cached_data = cache.get(cache_key)
        assert cached_data == test_result


class TestDryRunMode(TestCase):
    """Test dry-run mode for subscription/polling system."""

    def setUp(self):
        """Set up test fixtures."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        current_canonical_id.set(None)

    def test_generate_cache_key_for_subscription_returns_cache_key(self):
        """Test that generate_cache_key_for_subscription returns cache key and query type."""
        user = User.objects.create_user(username="testuser", password="testpass")
        queryset = User.objects.filter(username="testuser")
        txn_id = "txn-dry-002"
        current_canonical_id.set(txn_id)

        operation_context = "read:fields=default"

        # Should return cache key with query type
        result = generate_cache_key_for_subscription(queryset, operation_context=operation_context, query_type="read")

        assert result is not None
        assert "cache_key" in result
        assert "query_type" in result
        assert result["cache_key"].startswith("statezero:query:")
        assert result["query_type"] == "read"
        assert result["metadata"]["dry_run"] is True

    def test_generate_cache_key_no_canonical_id_returns_none(self):
        """Test that generate_cache_key_for_subscription returns None when no canonical_id is set."""
        queryset = User.objects.all()
        current_canonical_id.set(None)

        # Should return None when no canonical_id
        result = generate_cache_key_for_subscription(queryset, operation_context=None, query_type="read")
        assert result is None

    def test_generate_cache_key_matches_write_path(self):
        """Test that generated cache key matches the key used by write path."""
        user = User.objects.create_user(username="testuser", password="testpass")
        queryset = User.objects.filter(username="testuser")
        txn_id = "txn-dry-003"
        current_canonical_id.set(txn_id)

        operation_context = "read:fields=default"

        # Get cache key from subscription generator
        subscription_result = generate_cache_key_for_subscription(queryset, operation_context=operation_context, query_type="read")
        subscription_cache_key = subscription_result["cache_key"]

        # Generate cache key manually (simulating write path)
        sql_data = _get_sql_from_queryset(queryset)
        sql, params = sql_data
        write_cache_key = _get_cache_key(sql, params, txn_id, operation_context)

        # Cache keys should match
        assert subscription_cache_key == write_cache_key

    def test_generate_cache_key_different_operation_contexts(self):
        """Test that different operation contexts produce different cache keys."""
        queryset = User.objects.all()
        txn_id = "txn-dry-004"
        current_canonical_id.set(txn_id)

        # Get cache key for read operation
        read_result = generate_cache_key_for_subscription(queryset, operation_context="read:fields=default", query_type="read")
        read_key = read_result["cache_key"]

        # Get cache key for count operation
        count_result = generate_cache_key_for_subscription(queryset, operation_context="count:id", query_type="aggregate")
        count_key = count_result["cache_key"]

        # Keys should be different
        assert read_key != count_key

    def test_generate_cache_key_query_types(self):
        """Test that query_type is correctly set for read vs aggregate."""
        queryset = User.objects.all()
        txn_id = "txn-dry-005"
        current_canonical_id.set(txn_id)

        # Read query
        read_result = generate_cache_key_for_subscription(queryset, operation_context="read:fields=default", query_type="read")
        assert read_result["query_type"] == "read"

        # Aggregate query
        agg_result = generate_cache_key_for_subscription(queryset, operation_context="count:id", query_type="aggregate")
        assert agg_result["query_type"] == "aggregate"

    def test_generate_cache_key_function(self):
        """Test the generate_cache_key helper function directly."""
        from statezero.core.query_cache import generate_cache_key

        user = User.objects.create_user(username="testuser", password="testpass")
        queryset = User.objects.filter(username="testuser")
        txn_id = "txn-dry-005"
        current_canonical_id.set(txn_id)

        # Generate cache key
        cache_key = generate_cache_key(queryset, operation_context="read:fields=default")

        assert cache_key is not None
        assert cache_key.startswith("statezero:query:")
        assert isinstance(cache_key, str)

    def test_generate_cache_key_no_canonical_id(self):
        """Test that generate_cache_key returns None when no canonical_id."""
        from statezero.core.query_cache import generate_cache_key

        queryset = User.objects.all()
        current_canonical_id.set(None)

        # Should return None
        cache_key = generate_cache_key(queryset, operation_context=None)
        assert cache_key is None


class TestPermissionSafety(TestCase):
    """Test that permissions create different cache keys (write path safety)."""

    def setUp(self):
        """Set up test fixtures."""
        cache.clear()
        # Create test users
        self.user1 = User.objects.create_user(username="user1", password="pass")
        self.user2 = User.objects.create_user(username="user2", password="pass")

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        current_canonical_id.set(None)

    def test_different_filters_different_cache_keys(self):
        """
        Test that different filters (from permissions) create different cache keys.

        This is the core insight: permissions create different SQL, which
        automatically creates different cache keys for the write path.
        """
        txn_id = "txn-test-001"

        # User 1's queryset (filtered to their data)
        qs_user1 = User.objects.filter(id=self.user1.id)

        # User 2's queryset (filtered to their data)
        qs_user2 = User.objects.filter(id=self.user2.id)

        # Get cache keys for each
        sql1_data = _get_sql_from_queryset(qs_user1)
        sql2_data = _get_sql_from_queryset(qs_user2)

        assert sql1_data is not None
        assert sql2_data is not None

        sql1, params1 = sql1_data
        sql2, params2 = sql2_data

        key1 = _get_cache_key(sql1, params1, txn_id)
        key2 = _get_cache_key(sql2, params2, txn_id)

        # Different permissions should produce different cache keys
        assert key1 != key2


class TestAggregateQueries(TestCase):
    """Test that aggregate queries work with write path caching."""

    def setUp(self):
        """Set up test fixtures."""
        cache.clear()
        User.objects.create_user(username="user1", password="pass")
        User.objects.create_user(username="user2", password="pass")

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        current_canonical_id.set(None)

    def test_aggregate_query_sql_extraction(self):
        """Test that we can extract SQL from aggregate queries (needed for write path)."""
        from django.db.models import Count

        queryset = User.objects.all()

        # Get SQL before aggregation (this is what we'll use for cache key)
        sql_data = _get_sql_from_queryset(queryset)

        assert sql_data is not None
        sql, params = sql_data
        assert "SELECT" in sql.upper()

    def test_cache_aggregate_result_write_path(self):
        """Test that aggregate results can be written to cache."""
        queryset = User.objects.all()
        txn_id = "txn-aggregate-001"
        current_canonical_id.set(txn_id)

        # Cache an aggregate result
        aggregate_result = {
            "data": {"id_count": 2},
            "metadata": {"aggregate": True},
        }
        cache_query_result(queryset, aggregate_result)

        # Verify it was written (testing write path)
        sql_data = _get_sql_from_queryset(queryset)
        assert sql_data is not None
        sql, params = sql_data
        cache_key = _get_cache_key(sql, params, txn_id, None)
        cached_data = cache.get(cache_key)
        assert cached_data == aggregate_result


# Integration Tests
from django.urls import reverse
from rest_framework.test import APITestCase
from tests.django_app.models import DummyModel, DummyRelatedModel


from django.test import TransactionTestCase


class NonCachingIntegrationTests(TransactionTestCase):
    """Integration tests for non-caching features (search, ordering, pagination)."""

    def setUp(self):
        """Set up test fixtures."""
        cache.clear()
        # Clean up any existing data
        DummyModel.objects.all().delete()
        DummyRelatedModel.objects.all().delete()
        User.objects.all().delete()

        # Create a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create test data
        self.related1 = DummyRelatedModel.objects.create(name="Related1")
        self.related2 = DummyRelatedModel.objects.create(name="Related2")

        DummyModel.objects.create(name="TestA", value=10, related=self.related1)
        DummyModel.objects.create(name="TestB", value=20, related=self.related1)
        DummyModel.objects.create(name="TestC", value=30, related=self.related2)
        DummyModel.objects.create(name="TestD", value=40, related=self.related2)

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        DummyModel.objects.all().delete()
        DummyRelatedModel.objects.all().delete()
        User.objects.all().delete()

    def test_search_works_without_intervention(self):
        """Test that search works correctly."""
        from tests.django_app.models import DummyModel
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Create test items
        DummyModel.objects.all().delete()
        DummyModel.objects.create(name="Apple", value=10)
        DummyModel.objects.create(name="Banana", value=20)
        DummyModel.objects.create(name="Apricot", value=30)
        DummyModel.objects.create(name="Cherry", value=40)

        # Search for items starting with "Ap" - client sends search inside query
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "search": {
                        "searchQuery": "Ap",
                        "searchFields": ["name"]
                    }
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)

        ids = response.data["data"]["data"]
        included = response.data["data"]["included"]["django_app.dummymodel"]
        names = [included[id]["name"] for id in ids]

        # Should return Apple and Apricot
        self.assertEqual(len(names), 2)
        self.assertIn("Apple", names)
        self.assertIn("Apricot", names)

    def test_ordering_works_without_cache(self):
        """Test that ordering actually works (sanity check)."""
        from tests.django_app.models import DummyModel
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Create 10 items with different names
        DummyModel.objects.all().delete()
        for i in range(10):
            DummyModel.objects.create(name=f"Item{i:02d}", value=i * 10)

        # First request: ascending order, first page (limit 5)
        payload1 = {
            "ast": {
                "query": {
                    "type": "read",
                    "orderBy": ["name"],
                },
                "serializerOptions": {"limit": 5, "offset": 0},
            }
        }

        response1 = self.client.post(url, data=payload1, format="json")
        self.assertEqual(response1.status_code, 200)
        ids1 = response1.data["data"]["data"]
        included1 = response1.data["data"]["included"]["django_app.dummymodel"]
        names1 = [included1[id]["name"] for id in ids1]

        # Second request: descending order, first page (limit 5)
        payload2 = {
            "ast": {
                "query": {
                    "type": "read",
                    "orderBy": ["-name"],
                },
                "serializerOptions": {"limit": 5, "offset": 0},
            }
        }

        response2 = self.client.post(url, data=payload2, format="json")
        self.assertEqual(response2.status_code, 200)
        ids2 = response2.data["data"]["data"]
        included2 = response2.data["data"]["included"]["django_app.dummymodel"]
        names2 = [included2[id]["name"] for id in ids2]

        # Verify ordering
        self.assertEqual(names1[0], "Item00")
        self.assertEqual(names1[4], "Item04")
        self.assertEqual(names2[0], "Item09")
        self.assertEqual(names2[4], "Item05")

        # The two lists should have NO overlap
        self.assertEqual(len(set(names1) & set(names2)), 0,
                        f"Ascending and descending should have no overlap. Got: {names1} vs {names2}")

    def test_pagination_with_permission_filter_queryset(self):
        """
        Test that pagination works with permission classes that filter the queryset
        in bulk_operation_allowed.

        This test reproduces the original bug where passing a sliced queryset to
        check_bulk_permissions would cause:
        "TypeError: Cannot filter a query once a slice has been taken"

        The fix was to call check_bulk_permissions BEFORE slicing the queryset.
        """
        from tests.django_app.models import NameFilterCustomPKModel
        from statezero.adaptors.django.config import registry
        from statezero.core.config import ModelConfig
        from tests.django_app.permissions import FilterInBulkPermission

        # Save original config
        original_config = registry._models_config.get(NameFilterCustomPKModel)

        # Override registration with FilterInBulkPermission at runtime for this test
        registry._models_config[NameFilterCustomPKModel] = ModelConfig(
            model=NameFilterCustomPKModel,
            filterable_fields={"name", "custom_pk"},
            searchable_fields={"name"},
            ordering_fields={"name", "custom_pk"},
            permissions=[FilterInBulkPermission],
        )

        try:
            url = reverse("statezero:model_view", args=["django_app.NameFilterCustomPKModel"])

            # Clean up and create test data
            NameFilterCustomPKModel.objects.all().delete()

            # Create items - the FilterInBulkPermission filters by name__startswith="Allowed"
            # Create 5 items that match the permission filter
            for i in range(5):
                NameFilterCustomPKModel.objects.create(name=f"Allowed{i:02d}")

            # Create 5 items that don't match (should be filtered out by permission)
            for i in range(5):
                NameFilterCustomPKModel.objects.create(name=f"Denied{i:02d}")

            # Request with pagination (limit 3, offset 0)
            # This would have failed before the fix with:
            # "TypeError: Cannot filter a query once a slice has been taken"
            # Because the permission's bulk_operation_allowed would receive a sliced queryset
            payload = {
                "ast": {
                    "query": {
                        "type": "read",
                    },
                    "serializerOptions": {"limit": 3, "offset": 0},
                }
            }

            response = self.client.post(url, data=payload, format="json")
            self.assertEqual(response.status_code, 200)

            ids = response.data["data"]["data"]
            included = response.data["data"]["included"]["django_app.namefiltercustompkmodel"]
            names = [included[id]["name"] for id in ids]

            # Should only return 3 items due to limit
            self.assertEqual(len(names), 3)

            # All returned items should start with "Allowed" (permission filter)
            for name in names:
                self.assertTrue(name.startswith("Allowed"),
                              f"Expected name to start with 'Allowed', got {name}")

            # Test second page
            payload2 = {
                "ast": {
                    "query": {
                        "type": "read",
                    },
                    "serializerOptions": {"limit": 3, "offset": 3},
                }
            }

            response2 = self.client.post(url, data=payload2, format="json")
            self.assertEqual(response2.status_code, 200)

            ids2 = response2.data["data"]["data"]
            included2 = response2.data["data"]["included"]["django_app.namefiltercustompkmodel"]
            names2 = [included2[id]["name"] for id in ids2]

            # Should return 2 items (5 total matching, 3 on first page, 2 on second)
            self.assertEqual(len(names2), 2)

            # All should still start with "Allowed"
            for name in names2:
                self.assertTrue(name.startswith("Allowed"),
                              f"Expected name to start with 'Allowed', got {name}")
        finally:
            # Restore original registration
            if original_config:
                registry._models_config[NameFilterCustomPKModel] = original_config
            else:
                # If it wasn't registered before, remove it
                registry._models_config.pop(NameFilterCustomPKModel, None)
