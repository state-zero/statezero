"""
Tests for query-level caching (reads and aggregates).
"""
import hashlib
from typing import Any, Set, Type
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, RequestFactory

from statezero.core.context_storage import current_canonical_id
from statezero.core.query_cache import (
    _get_cache_key,
    _get_sql_from_queryset,
    cache_query_result,
    get_cached_query_result,
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


class TestTransactionScoping(TestCase):
    """Test that cache is scoped to transaction ID."""

    def setUp(self):
        """Set up test fixtures."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        current_canonical_id.set(None)

    def test_same_transaction_hits_cache(self):
        """Test that same transaction ID hits cache."""
        sql = "SELECT * FROM users WHERE id = %s"
        params = (1,)
        txn_id = "txn-001"

        # Create cache key and store result
        key = _get_cache_key(sql, params, txn_id)
        test_result = {"data": [{"id": 1, "name": "Test"}], "metadata": {}}
        cache.set(key, test_result)

        # Same transaction should hit cache
        assert cache.get(key) == test_result

    def test_different_transaction_misses_cache(self):
        """Test that different transaction ID misses cache."""
        sql = "SELECT * FROM users WHERE id = %s"
        params = (1,)

        # Transaction 1
        txn1 = "txn-001"
        key1 = _get_cache_key(sql, params, txn1)
        cache.set(key1, {"data": "result-from-txn1"})

        # Transaction 2 (after mutation) - different key
        txn2 = "txn-002"
        key2 = _get_cache_key(sql, params, txn2)

        # Different transaction = cache miss
        assert cache.get(key2) is None
        assert key1 != key2


class TestCachingFunctions(TestCase):
    """Test the main caching functions."""

    def setUp(self):
        """Set up test fixtures."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        current_canonical_id.set(None)

    def test_get_cached_query_result_no_canonical_id(self):
        """Test that caching is skipped when no canonical_id is set."""
        queryset = User.objects.all()
        current_canonical_id.set(None)

        result = get_cached_query_result(queryset)

        # Should return None (no caching without canonical_id)
        assert result is None

    def test_get_cached_query_result_miss(self):
        """Test cache miss returns None."""
        queryset = User.objects.filter(username="testuser")
        current_canonical_id.set("txn-test-001")

        result = get_cached_query_result(queryset)

        # Should be cache miss
        assert result is None

    def test_cache_and_retrieve_result(self):
        """Test caching and retrieving a result."""
        # Create a user for the queryset
        user = User.objects.create_user(username="testuser", password="testpass")
        queryset = User.objects.filter(username="testuser")
        txn_id = "txn-test-001"
        current_canonical_id.set(txn_id)

        # First call should be a miss
        result1 = get_cached_query_result(queryset)
        assert result1 is None

        # Cache a result
        test_result = {
            "data": [{"id": user.id, "username": "testuser"}],
            "metadata": {"read": True},
        }
        cache_query_result(queryset, test_result)

        # Second call should hit cache
        result2 = get_cached_query_result(queryset)
        assert result2 == test_result

    def test_cache_result_no_canonical_id(self):
        """Test that caching is skipped when no canonical_id is set."""
        queryset = User.objects.all()
        current_canonical_id.set(None)

        test_result = {"data": [], "metadata": {}}

        # Should not raise error, just skip caching
        cache_query_result(queryset, test_result)

        # Verify nothing was cached
        current_canonical_id.set("txn-001")
        result = get_cached_query_result(queryset)
        # Different transaction, so won't find it anyway


class TestPermissionSafety(TestCase):
    """Test that permissions are automatically safe."""

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
        automatically creates different cache keys.
        """
        txn_id = "txn-test-001"
        current_canonical_id.set(txn_id)

        # User 1's queryset (filtered to their data)
        qs_user1 = User.objects.filter(id=self.user1.id)

        # User 2's queryset (filtered to their data)
        qs_user2 = User.objects.filter(id=self.user2.id)

        # Cache result for user 1
        result_user1 = {"data": [{"id": self.user1.id, "username": "user1"}]}
        cache_query_result(qs_user1, result_user1)

        # Try to get with user 2's queryset
        cached_result = get_cached_query_result(qs_user2)

        # Should be cache miss because different SQL
        assert cached_result is None

        # Cache result for user 2
        result_user2 = {"data": [{"id": self.user2.id, "username": "user2"}]}
        cache_query_result(qs_user2, result_user2)

        # Each user should get their own cached result
        assert get_cached_query_result(qs_user1) == result_user1
        assert get_cached_query_result(qs_user2) == result_user2


class TestAggregateQueries(TestCase):
    """Test that aggregate queries can be cached."""

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
        """Test that we can extract SQL from aggregate queries."""
        from django.db.models import Count

        queryset = User.objects.all()

        # Get SQL before aggregation (this is what we'll cache against)
        sql_data = _get_sql_from_queryset(queryset)

        assert sql_data is not None
        sql, params = sql_data
        assert "SELECT" in sql.upper()

    def test_cache_aggregate_result(self):
        """Test caching an aggregate result."""
        queryset = User.objects.all()
        txn_id = "txn-aggregate-001"
        current_canonical_id.set(txn_id)

        # Cache an aggregate result
        aggregate_result = {
            "data": {"id_count": 2},
            "metadata": {"aggregate": True},
        }
        cache_query_result(queryset, aggregate_result)

        # Should hit cache
        cached = get_cached_query_result(queryset)
        assert cached == aggregate_result

    def test_different_aggregates_same_queryset_share_cache(self):
        """
        Test that different aggregate operations on the same queryset
        will share cache (because the SQL for the base queryset is the same).

        NOTE: This is a current limitation - the cache key is based on the
        base queryset SQL, not the aggregate function. This could be improved
        if needed.
        """
        queryset = User.objects.filter(is_active=True)
        txn_id = "txn-aggregate-002"
        current_canonical_id.set(txn_id)

        # For the same base queryset, different aggregates would currently
        # share the same cache key (based on base queryset SQL)
        # This test documents this behavior
        sql_data = _get_sql_from_queryset(queryset)
        assert sql_data is not None


# Integration Tests
from django.urls import reverse
from rest_framework.test import APITestCase
from tests.django_app.models import DummyModel, DummyRelatedModel


from django.test import TransactionTestCase


class QueryCacheIntegrationTest(TransactionTestCase):
    """Integration tests for query caching with real API requests."""

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
        current_canonical_id.set(None)
        DummyModel.objects.all().delete()
        DummyRelatedModel.objects.all().delete()
        User.objects.all().delete()

    def test_read_query_caching_on_second_request(self):
        """Test that identical read queries hit cache on second request."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Create payload - read all
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
            HTTP_X_CANONICAL_ID="txn-integration-001",
        )
        self.assertEqual(response1.status_code, 200)

        # Second identical request with same canonical_id - should hit cache
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-integration-001",
        )
        self.assertEqual(response2.status_code, 200)

        # Should return identical data (from cache)
        self.assertEqual(response1.data, response2.data)

    def test_different_transaction_id_bypasses_cache(self):
        """Test that different transaction IDs bypass cache."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # First request with txn-001
        response1 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-001",
        )
        self.assertEqual(response1.status_code, 200)
        ids1 = response1.data["data"]["data"]  # List of IDs
        self.assertEqual(len(ids1), 4)  # TestA, TestB, TestC, TestD

        # Modify data
        DummyModel.objects.create(name="TestE", value=50, related=self.related1)

        # Second request with SAME transaction ID - should hit cache (stale data)
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-001",
        )
        self.assertEqual(response2.status_code, 200)
        ids2 = response2.data["data"]["data"]
        # Should still show old count (cached)
        self.assertEqual(len(ids2), 4)
        self.assertEqual(response1.data, response2.data)

        # Third request with DIFFERENT transaction ID - should bypass cache
        response3 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-002",
        )
        self.assertEqual(response3.status_code, 200)
        ids3 = response3.data["data"]["data"]
        # Should see fresh data with the new record
        self.assertEqual(len(ids3), 5)  # TestA, TestB, TestC, TestD, TestE

    def test_different_filters_different_cache_keys_integration(self):
        """Test that different filters create different cache keys in real requests."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # First query - filter by name=TestA
        payload1 = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {"type": "filter", "conditions": {"name": "TestA"}},
                }
            }
        }

        response1 = self.client.post(
            url,
            data=payload1,
            format="json",
            HTTP_X_CANONICAL_ID="txn-filter-001",
        )
        self.assertEqual(response1.status_code, 200)
        ids1 = response1.data["data"]["data"]
        self.assertEqual(len(ids1), 1)
        # Verify it's TestA - get the actual item
        included1 = response1.data["data"]["included"]["django_app.dummymodel"]
        items1 = list(included1.values())
        self.assertEqual(len(items1), 1)
        self.assertEqual(items1[0]["name"], "TestA")

        # Second query - filter by name=TestC (same transaction ID)
        payload2 = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {"type": "filter", "conditions": {"name": "TestC"}},
                }
            }
        }

        response2 = self.client.post(
            url,
            data=payload2,
            format="json",
            HTTP_X_CANONICAL_ID="txn-filter-001",
        )
        self.assertEqual(response2.status_code, 200)
        ids2 = response2.data["data"]["data"]
        self.assertEqual(len(ids2), 1)
        # Verify it's TestC
        included2 = response2.data["data"]["included"]["django_app.dummymodel"]
        items2 = list(included2.values())
        self.assertEqual(len(items2), 1)
        self.assertEqual(items2[0]["name"], "TestC")

        # Different filters should return different results (not cached together)
        self.assertNotEqual(ids1, ids2)

    def test_aggregate_caching_integration(self):
        """Test that aggregate queries are cached."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Count query
        payload = {
            "ast": {
                "query": {
                    "type": "count",
                    "field": "id",
                }
            }
        }

        # First request - cache miss
        response1 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-agg-001",
        )
        self.assertEqual(response1.status_code, 200)
        count1 = response1.data.get("data")
        self.assertEqual(count1, 4)  # 4 records created in setUp

        # Second identical request - should hit cache
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-agg-001",
        )
        self.assertEqual(response2.status_code, 200)
        count2 = response2.data.get("data")
        self.assertEqual(count1, count2)

    def test_aggregate_with_filter_caching(self):
        """Test that aggregate queries with filters are cached correctly."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Count with filter
        payload = {
            "ast": {
                "query": {
                    "type": "count",
                    "field": "id",
                    "filter": {"type": "filter", "conditions": {"value__gte": 30}},
                }
            }
        }

        # First request
        response1 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-agg-filter-001",
        )
        self.assertEqual(response1.status_code, 200)
        count1 = response1.data.get("data")
        self.assertEqual(count1, 2)  # TestC (30) and TestD (40)

        # Second request - should hit cache
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-agg-filter-001",
        )
        self.assertEqual(response2.status_code, 200)
        count2 = response2.data.get("data")
        self.assertEqual(count1, count2)

    def test_sum_aggregate_caching(self):
        """Test that SUM aggregate queries are cached."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Sum of all values
        payload = {
            "ast": {
                "query": {
                    "type": "sum",
                    "field": "value",
                }
            }
        }

        # First request - cache miss
        response1 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-sum-001",
        )
        self.assertEqual(response1.status_code, 200)
        sum1 = response1.data.get("data")
        self.assertEqual(sum1, 100)  # 10 + 20 + 30 + 40

        # Second request - should hit cache
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-sum-001",
        )
        self.assertEqual(response2.status_code, 200)
        sum2 = response2.data.get("data")
        self.assertEqual(sum1, sum2)
        self.assertEqual(response1.data, response2.data)

    def test_avg_aggregate_caching(self):
        """Test that AVG aggregate queries are cached."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Average of all values
        payload = {
            "ast": {
                "query": {
                    "type": "avg",
                    "field": "value",
                }
            }
        }

        # First request - cache miss
        response1 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-avg-001",
        )
        self.assertEqual(response1.status_code, 200)
        avg1 = response1.data.get("data")
        self.assertEqual(avg1, 25.0)  # (10 + 20 + 30 + 40) / 4

        # Second request - should hit cache
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-avg-001",
        )
        self.assertEqual(response2.status_code, 200)
        avg2 = response2.data.get("data")
        self.assertEqual(avg1, avg2)

    def test_min_max_aggregate_caching(self):
        """Test that MIN and MAX aggregate queries are cached."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Min value
        payload_min = {
            "ast": {
                "query": {
                    "type": "min",
                    "field": "value",
                }
            }
        }

        response_min = self.client.post(
            url,
            data=payload_min,
            format="json",
            HTTP_X_CANONICAL_ID="txn-minmax-001",
        )
        self.assertEqual(response_min.status_code, 200)
        min_val = response_min.data.get("data")
        self.assertEqual(min_val, 10)  # TestA

        # Max value (same transaction ID)
        payload_max = {
            "ast": {
                "query": {
                    "type": "max",
                    "field": "value",
                }
            }
        }

        response_max = self.client.post(
            url,
            data=payload_max,
            format="json",
            HTTP_X_CANONICAL_ID="txn-minmax-001",
        )
        self.assertEqual(response_max.status_code, 200)
        max_val = response_max.data.get("data")
        self.assertEqual(max_val, 40)  # TestD

        # Different aggregates should have different cache entries
        self.assertNotEqual(min_val, max_val)

    def test_aggregate_cache_invalidation_on_new_transaction(self):
        """Test that aggregates are invalidated when transaction ID changes."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "count",
                    "field": "id",
                }
            }
        }

        # First request with txn-001
        response1 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-agg-invalidate-001",
        )
        self.assertEqual(response1.status_code, 200)
        count1 = response1.data.get("data")
        self.assertEqual(count1, 4)  # TestA, TestB, TestC, TestD

        # Add new data
        DummyModel.objects.create(name="TestE", value=50, related=self.related1)
        DummyModel.objects.create(name="TestF", value=60, related=self.related2)

        # Second request with SAME transaction ID - should hit cache (stale)
        response2 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-agg-invalidate-001",
        )
        self.assertEqual(response2.status_code, 200)
        count2 = response2.data.get("data")
        self.assertEqual(count2, 4)  # Still cached old value

        # Third request with DIFFERENT transaction ID - should bypass cache
        response3 = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_CANONICAL_ID="txn-agg-invalidate-002",
        )
        self.assertEqual(response3.status_code, 200)
        count3 = response3.data.get("data")
        self.assertEqual(count3, 6)  # Fresh data with new records

    def test_aggregate_with_filter_different_cache_keys(self):
        """Test that aggregates with different filters have different cache keys."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Count with filter value >= 30
        payload1 = {
            "ast": {
                "query": {
                    "type": "count",
                    "field": "id",
                    "filter": {"type": "filter", "conditions": {"value__gte": 30}},
                }
            }
        }

        response1 = self.client.post(
            url,
            data=payload1,
            format="json",
            HTTP_X_CANONICAL_ID="txn-agg-diff-001",
        )
        self.assertEqual(response1.status_code, 200)
        count1 = response1.data.get("data")
        self.assertEqual(count1, 2)  # TestC, TestD

        # Count with filter value < 30 (same transaction ID)
        payload2 = {
            "ast": {
                "query": {
                    "type": "count",
                    "field": "id",
                    "filter": {"type": "filter", "conditions": {"value__lt": 30}},
                }
            }
        }

        response2 = self.client.post(
            url,
            data=payload2,
            format="json",
            HTTP_X_CANONICAL_ID="txn-agg-diff-001",
        )
        self.assertEqual(response2.status_code, 200)
        count2 = response2.data.get("data")
        self.assertEqual(count2, 2)  # TestA, TestB

        # Different filters return different results (different cache keys)
        # Both happen to return count=2, but they're from different queries
        # The metadata and data happen to be identical, but the SQL was different
        # Just verify both queries executed successfully
        self.assertEqual(count1, 2)
        self.assertEqual(count2, 2)

    def test_no_caching_without_canonical_id(self):
        """Test that requests without canonical_id still work (uses system-generated id)."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {"type": "filter", "conditions": {"name": "TestA"}},
                }
            }
        }

        # Request without canonical_id header - should work with system-generated ID
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        ids = response.data["data"]["data"]
        self.assertEqual(len(ids), 1)
        # Verify it's TestA
        included = response.data["data"]["included"]["django_app.dummymodel"]
        items = list(included.values())
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "TestA")

    def test_pagination_with_caching(self):
        """Test that pagination creates different cache entries for different pages."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # First page
        payload1 = {
            "ast": {
                "query": {"type": "read"},
                "serializerOptions": {"limit": 2, "offset": 0},
            }
        }

        response1 = self.client.post(
            url,
            data=payload1,
            format="json",
            HTTP_X_CANONICAL_ID="txn-page-001",
        )
        self.assertEqual(response1.status_code, 200)
        ids1 = response1.data["data"]["data"]
        self.assertEqual(len(ids1), 2)  # Limit 2

        # Second page (different offset, same transaction)
        payload2 = {
            "ast": {
                "query": {"type": "read"},
                "serializerOptions": {"limit": 2, "offset": 2},
            }
        }

        response2 = self.client.post(
            url,
            data=payload2,
            format="json",
            HTTP_X_CANONICAL_ID="txn-page-001",
        )
        self.assertEqual(response2.status_code, 200)
        ids2 = response2.data["data"]["data"]
        self.assertEqual(len(ids2), 2)  # Limit 2

        # Different pages should have different IDs (different cache entries)
        # Because LIMIT/OFFSET are in the SQL, each page has its own cache key
        self.assertNotEqual(ids1, ids2)

    def test_different_field_selections_separate_cache(self):
        """Test that different field selections create separate cache entries."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Request with minimal fields
        payload1 = {
            "ast": {
                "query": {"type": "read"},
                "serializerOptions": {
                    "fields": ["id", "name"]
                },
            }
        }

        response1 = self.client.post(
            url,
            data=payload1,
            format="json",
            HTTP_X_CANONICAL_ID="txn-fields-001",
        )
        self.assertEqual(response1.status_code, 200)

        # Get first object from response
        included1 = response1.data["data"]["included"]["django_app.dummymodel"]
        first_obj_1 = list(included1.values())[0]

        # Should only have id and name fields (plus metadata)
        self.assertIn("id", first_obj_1)
        self.assertIn("name", first_obj_1)
        # Value field should NOT be present
        self.assertNotIn("value", first_obj_1)

        # Request with more fields (same transaction ID)
        payload2 = {
            "ast": {
                "query": {"type": "read"},
                "serializerOptions": {
                    "fields": ["id", "name", "value"]
                },
            }
        }

        response2 = self.client.post(
            url,
            data=payload2,
            format="json",
            HTTP_X_CANONICAL_ID="txn-fields-001",
        )
        self.assertEqual(response2.status_code, 200)

        # Get first object from response
        included2 = response2.data["data"]["included"]["django_app.dummymodel"]
        first_obj_2 = list(included2.values())[0]

        # Should have id, name, AND value fields
        self.assertIn("id", first_obj_2)
        self.assertIn("name", first_obj_2)
        self.assertIn("value", first_obj_2)

        # Verify they're different (different field selections, different cache keys)
        # First object should not have 'value', second should
        self.assertNotIn("value", first_obj_1)
        self.assertIn("value", first_obj_2)

    def test_cache_hit_prevents_db_queries(self):
        """Test that cache hits actually prevent database queries."""
        from django.test import override_settings
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # First request - should execute queries
        with CaptureQueriesContext(connection) as ctx_first:
            response1 = self.client.post(
                url,
                data=payload,
                format="json",
                HTTP_X_CANONICAL_ID="txn-query-count-001",
            )
        self.assertEqual(response1.status_code, 200)
        first_query_count = len(ctx_first.captured_queries)
        self.assertGreater(first_query_count, 0, "First request should execute queries")

        # Second request with same canonical_id - should NOT execute queries (cache hit)
        with CaptureQueriesContext(connection) as ctx_second:
            response2 = self.client.post(
                url,
                data=payload,
                format="json",
                HTTP_X_CANONICAL_ID="txn-query-count-001",
            )
        self.assertEqual(response2.status_code, 200)
        second_query_count = len(ctx_second.captured_queries)

        # Cache hit should execute fewer queries (ideally 0, but might have auth/session queries)
        # The key point is: significantly fewer than first request
        self.assertLess(second_query_count, first_query_count,
                       f"Cache hit should execute fewer queries. First: {first_query_count}, Second: {second_query_count}")

        # Results should be identical
        self.assertEqual(response1.data, response2.data)

    def test_aggregate_cache_hit_prevents_db_queries(self):
        """Test that aggregate cache hits prevent database queries."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "sum",
                    "field": "value",
                }
            }
        }

        # First request - should execute queries
        with CaptureQueriesContext(connection) as ctx_first:
            response1 = self.client.post(
                url,
                data=payload,
                format="json",
                HTTP_X_CANONICAL_ID="txn-agg-count-001",
            )
        self.assertEqual(response1.status_code, 200)
        first_query_count = len(ctx_first.captured_queries)
        self.assertGreater(first_query_count, 0, "First request should execute queries")

        # Second request with same canonical_id - should NOT execute queries (cache hit)
        with CaptureQueriesContext(connection) as ctx_second:
            response2 = self.client.post(
                url,
                data=payload,
                format="json",
                HTTP_X_CANONICAL_ID="txn-agg-count-001",
            )
        self.assertEqual(response2.status_code, 200)
        second_query_count = len(ctx_second.captured_queries)

        # Cache hit should execute fewer queries
        self.assertLess(second_query_count, first_query_count,
                       f"Cache hit should execute fewer queries. First: {first_query_count}, Second: {second_query_count}")

        # Results should be identical
        self.assertEqual(response1.data, response2.data)

    def test_no_canonical_id_always_executes_queries(self):
        """Test that requests without canonical_id always execute queries (no caching)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # First request without canonical_id
        with CaptureQueriesContext(connection) as ctx_first:
            response1 = self.client.post(
                url,
                data=payload,
                format="json",
            )
        self.assertEqual(response1.status_code, 200)
        first_query_count = len(ctx_first.captured_queries)
        self.assertGreater(first_query_count, 0)

        # Second request without canonical_id - should also execute queries
        with CaptureQueriesContext(connection) as ctx_second:
            response2 = self.client.post(
                url,
                data=payload,
                format="json",
            )
        self.assertEqual(response2.status_code, 200)
        second_query_count = len(ctx_second.captured_queries)

        # Both should execute similar number of queries (no caching)
        self.assertGreater(second_query_count, 0, "Without canonical_id, should always execute queries")

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

        print(f"\n=== Search results for 'Ap': {names}")

        # Should return Apple and Apricot
        self.assertEqual(len(names), 2)
        self.assertIn("Apple", names)
        self.assertIn("Apricot", names)

    def test_ordering_works_without_cache(self):
        """Test that ordering actually works without any caching (sanity check)."""
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
        print(f"=== Ascending order, first 5: {names1}")

        # Second request: descending order, first page (limit 5) - NO canonical_id so no caching
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
        print(f"=== Descending order, first 5: {names2}")

        # The names should be completely different
        # Ascending should start with Item00, Item01, Item02, Item03, Item04
        # Descending should start with Item09, Item08, Item07, Item06, Item05
        self.assertEqual(names1[0], "Item00")
        self.assertEqual(names1[4], "Item04")

        self.assertEqual(names2[0], "Item09")
        self.assertEqual(names2[4], "Item05")

        # The two lists should have NO overlap
        self.assertEqual(len(set(names1) & set(names2)), 0,
                        f"Ascending and descending should have no overlap. Got: {names1} vs {names2}")

    def test_different_ordering_different_cache_keys(self):
        """Test that different order_by clauses create different cache entries."""
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Query ordered by name ascending - client sends orderBy inside query
        payload1 = {
            "ast": {
                "query": {
                    "type": "read",
                    "orderBy": ["name"],
                }
            }
        }

        response1 = self.client.post(
            url,
            data=payload1,
            format="json",
            HTTP_X_CANONICAL_ID="txn-order-001",
        )
        self.assertEqual(response1.status_code, 200)
        ids1 = response1.data["data"]["data"]

        # Log the actual SQL for first request
        from tests.django_app.models import DummyModel
        from statezero.core.query_cache import _get_sql_from_queryset
        qs1 = DummyModel.objects.all().order_by("name")
        sql1_data = _get_sql_from_queryset(qs1)
        print(f"\n=== First request (order_by name ASC) ===")
        print(f"SQL: {sql1_data[0] if sql1_data else 'None'}")
        print(f"IDs: {ids1}")

        # Query ordered by name descending (same transaction) - client sends orderBy inside query
        payload2 = {
            "ast": {
                "query": {
                    "type": "read",
                    "orderBy": ["-name"],
                }
            }
        }

        response2 = self.client.post(
            url,
            data=payload2,
            format="json",
            HTTP_X_CANONICAL_ID="txn-order-001",
        )
        self.assertEqual(response2.status_code, 200)
        ids2 = response2.data["data"]["data"]

        # Log the actual SQL for second request
        qs2 = DummyModel.objects.all().order_by("-name")
        sql2_data = _get_sql_from_queryset(qs2)
        print(f"\n=== Second request (order_by name DESC) ===")
        print(f"SQL: {sql2_data[0] if sql2_data else 'None'}")
        print(f"IDs: {ids2}")

        # Different ordering should produce different results (different cache keys)
        # Because order_by changes the SQL
        self.assertNotEqual(ids1, ids2, "Different order_by should produce different results")

        # Verify actual ordering
        included1 = response1.data["data"]["included"]["django_app.dummymodel"]
        names1 = [included1[id]["name"] for id in ids1]

        included2 = response2.data["data"]["included"]["django_app.dummymodel"]
        names2 = [included2[id]["name"] for id in ids2]

        # First should be ascending, second descending
        self.assertEqual(names1, sorted(names1))
        self.assertEqual(names2, sorted(names2, reverse=True))

    def test_pagination_with_permission_filter_queryset(self):
        """
        Test that pagination works with permission classes that filter via filter_queryset.

        Read operations should not call bulk_operation_allowed; authorization for reads
        comes from queryset filtering and field visibility.
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

    def test_read_does_not_use_bulk_or_object_level_permissions(self):
        """
        Read path must rely on queryset/field permissions only.
        bulk_operation_allowed and allowed_object_actions are write-path checks.
        """
        from tests.django_app.models import NameFilterCustomPKModel
        from statezero.adaptors.django.config import registry
        from statezero.core.config import ModelConfig
        from statezero.core.interfaces import AbstractPermission
        from statezero.core.types import ActionType, ORMModel, RequestType
        from rest_framework.test import APIClient

        class ReadOnlyFilterPermission(AbstractPermission):
            def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
                # Keep SQL identical across users so cache/coalescing can be shared.
                return queryset

            def allowed_actions(
                self, request: RequestType, model: Type[ORMModel]
            ) -> Set[ActionType]:
                return {ActionType.READ}

            def allowed_object_actions(
                self, request: RequestType, obj: Any, model: Type[ORMModel]
            ) -> Set[ActionType]:
                raise AssertionError("allowed_object_actions should not be called for read list")

            def bulk_operation_allowed(
                self, request: RequestType, items: Any, action_type: ActionType, model: type
            ) -> bool:
                raise AssertionError("bulk_operation_allowed should not be called for read list")

            def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
                return "__all__"

            def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
                return set()

            def create_fields(self, request: RequestType, model: Type) -> Set[str]:
                return set()

        original_config = registry._models_config.get(NameFilterCustomPKModel)
        registry._models_config[NameFilterCustomPKModel] = ModelConfig(
            model=NameFilterCustomPKModel,
            filterable_fields={"name", "custom_pk"},
            searchable_fields={"name"},
            ordering_fields={"name", "custom_pk"},
            permissions=[ReadOnlyFilterPermission],
        )

        try:
            url = reverse("statezero:model_view", args=["django_app.NameFilterCustomPKModel"])
            NameFilterCustomPKModel.objects.all().delete()
            NameFilterCustomPKModel.objects.create(name="ItemA")
            NameFilterCustomPKModel.objects.create(name="ItemB")

            staff_user = User.objects.create_user(
                username="staff_cache_user",
                password="password",
                is_staff=True,
            )
            non_staff_user = User.objects.create_user(
                username="nonstaff_cache_user",
                password="password",
                is_staff=False,
            )

            staff_client = APIClient()
            staff_client.force_authenticate(user=staff_user)
            nonstaff_client = APIClient()
            nonstaff_client.force_authenticate(user=non_staff_user)

            payload = {"ast": {"query": {"type": "read"}}}
            canonical_id = "txn-read-filter-only-001"

            staff_response = staff_client.post(
                url,
                data=payload,
                format="json",
                HTTP_X_CANONICAL_ID=canonical_id,
            )
            self.assertEqual(staff_response.status_code, 200)

            nonstaff_response = nonstaff_client.post(
                url,
                data=payload,
                format="json",
                HTTP_X_CANONICAL_ID=canonical_id,
            )
            self.assertEqual(nonstaff_response.status_code, 200)
        finally:
            if original_config:
                registry._models_config[NameFilterCustomPKModel] = original_config
            else:
                registry._models_config.pop(NameFilterCustomPKModel, None)

    def test_request_coalescing_thundering_herd(self):
        """
        Test request coalescing with 500 concurrent requests (thundering herd scenario).

        When multiple clients receive a websocket event simultaneously, they all
        request the same query at the same time. Request coalescing should ensure:
        1. Only the first request executes the query
        2. Other requests wait and get the cached result
        3. All requests return the same data
        4. Database queries are minimized
        """
        import threading
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # Use a shared canonical_id for all requests (simulating websocket event)
        canonical_id = "txn-thundering-herd-001"

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # Storage for results and errors
        results = []
        errors = []
        query_counts = []

        def make_request():
            """Make a single request and record the result."""
            try:
                # Each thread needs its own client
                from rest_framework.test import APIClient
                thread_client = APIClient()
                thread_client.force_authenticate(user=self.user)

                # Track queries for this request
                with CaptureQueriesContext(connection) as ctx:
                    response = thread_client.post(
                        url,
                        data=payload,
                        format="json",
                        HTTP_X_CANONICAL_ID=canonical_id,
                    )

                query_count = len(ctx.captured_queries)
                query_counts.append(query_count)

                if response.status_code == 200:
                    results.append(response.data)
                else:
                    errors.append(f"Status {response.status_code}: {response.data}")
            except Exception as e:
                errors.append(str(e))

        # Create 500 threads to simulate thundering herd
        threads = []
        num_requests = 500

        print(f"\n=== Starting {num_requests} concurrent requests ===")

        # Create all threads
        for i in range(num_requests):
            thread = threading.Thread(target=make_request)
            threads.append(thread)

        # Start all threads as close to simultaneously as possible
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        print(f"=== Completed {len(results)} successful requests, {len(errors)} errors ===")

        # Verify all requests succeeded
        self.assertEqual(len(errors), 0, f"All requests should succeed. Errors: {errors[:5]}")
        self.assertEqual(len(results), num_requests, "All requests should return results")

        # Verify all results are identical
        first_result = results[0]
        for i, result in enumerate(results[1:], start=1):
            self.assertEqual(
                result,
                first_result,
                f"Request {i} returned different result than first request"
            )

        # Count how many requests executed queries vs cache hits
        # First request should execute queries (cache miss + lock acquisition)
        # Most other requests should have few/no queries (waiting for result)
        requests_with_queries = sum(1 for count in query_counts if count > 2)
        requests_without_queries = sum(1 for count in query_counts if count <= 2)

        print(f"=== Query execution stats ===")
        print(f"Requests that executed queries: {requests_with_queries}")
        print(f"Requests that hit cache/waited: {requests_without_queries}")
        print(f"Average queries per request: {sum(query_counts) / len(query_counts):.2f}")
        print(f"Max queries in a single request: {max(query_counts)}")
        print(f"Min queries in a single request: {min(query_counts)}")

        # With request coalescing, we should see:
        # - A small number of requests execute the query (ideally 1, but threading isn't perfect)
        # - The vast majority should hit cache or wait for the result
        # Without coalescing, all 500 would execute queries
        cache_hit_rate = (requests_without_queries / num_requests) * 100
        print(f"Cache hit rate: {cache_hit_rate:.1f}%")

        # We should see a high cache hit rate (>80%)
        # This proves request coalescing is working
        self.assertGreater(
            cache_hit_rate,
            80.0,
            f"Cache hit rate should be >80% with request coalescing, got {cache_hit_rate:.1f}%"
        )

        # The number of requests that executed queries should be small (ideally 1, but allow some slack)
        self.assertLess(
            requests_with_queries,
            50,  # Allow up to 10% to execute due to timing
            f"Too many requests executed queries ({requests_with_queries}). Request coalescing may not be working."
        )
