import hashlib
import json
import unittest
from typing import Any, Callable, Dict, Optional, Set, Type

import fakeredis

from statezero.core.caching import (CacheInvalidationEmitter, CachingMixin,
                                    RedisCacheBackend, RedisDependencyStore)
from statezero.core.types import ActionType
# Import your actual dummy model from tests.django_app.models.
from tests.django_app.models import \
    DummyModel  # adjust the import path as needed


def dummy_get_model_name(model: Any) -> str:
    """
    A helper that returns the model name in the format "app_label.model_name"
    using the model's _meta attribute.
    """
    if not isinstance(model, type):
        model = model.__class__
    return f"{model._meta.app_label}.{model._meta.model_name}"


# Create a dummy caching helper that uses the CachingMixin.
class DummyCaching(CachingMixin):
    def __init__(self, cache_backend, dependency_store):
        self.cache_backend = cache_backend
        self.dependency_store = dependency_store
        self.context = {}  # Needed for logging dependencies


class TestIndividualSignalInvalidation(unittest.TestCase):
    def setUp(self):
        # Set up a fake Redis client and caching components.
        self.redis_client = fakeredis.FakeStrictRedis()
        self.cache_backend = RedisCacheBackend(self.redis_client)
        self.dependency_store = RedisDependencyStore(self.redis_client)
        # Create our dummy caching helper.
        self.caching = DummyCaching(self.cache_backend, self.dependency_store)
        # Create an emitter that will simulate signal triggering.
        self.emitter = CacheInvalidationEmitter(
            cache_backend=self.cache_backend,
            dependency_store=self.dependency_store,
            get_model_name=dummy_get_model_name,
        )
        # Create a dummy model instance using the actual dummy model.
        self.instance = DummyModel.objects.create(name="TestModel")
        self.fields_map = {"name": {"name"}}
        self.depth = 0

        # Generate a cache key similar to production.
        key_data = {
            "model": dummy_get_model_name(DummyModel),
            "primary_key": self.instance.pk,
            "depth": self.depth,
            "fields_map": {k: sorted(list(v)) for k, v in self.fields_map.items()},
        }
        key_str = json.dumps(key_data, sort_keys=True)
        self.cache_key = hashlib.md5(key_str.encode("utf-8")).hexdigest()

    def tearDown(self):
        # Clean up the dummy instance.
        DummyModel.objects.all().delete()

    def test_cache_set_and_get(self):
        """Ensure that a value can be set and retrieved from the cache, and that dependency logging works."""
        value = {"result": "data"}
        # Initialize the dependency registry.
        self.caching.context["dependency_registry"] = {}
        # Log dependency for our dummy instance.
        self.caching.log_dependency(self.instance, dummy_get_model_name)
        # Cache the result.
        self.caching.cache_result(self.cache_key, value, ttl=60)

        # Retrieve value from cache.
        cached_value = self.cache_backend.get(self.cache_key)
        self.assertEqual(cached_value, value)

        # Verify that the dependency store has recorded the cache key.
        keys = self.dependency_store.get_cache_keys(
            dummy_get_model_name(self.instance), self.instance.pk
        )
        self.assertIn(self.cache_key, keys)

    def test_signal_based_invalidation(self):
        """
        Simulate a Django signal (such as post_save) by calling the emitter's emit method,
        and verify that the cache key is invalidated.
        """
        value = {"result": "data"}
        self.caching.context["dependency_registry"] = {}
        self.caching.log_dependency(self.instance, dummy_get_model_name)
        self.caching.cache_result(self.cache_key, value, ttl=60)

        # Verify that the key is in the cache.
        self.assertEqual(self.cache_backend.get(self.cache_key), value)

        # Now simulate triggering the invalidation signal.
        self.emitter.emit(ActionType.UPDATE, self.instance)

        # The cache key should be invalidated.
        self.assertIsNone(self.cache_backend.get(self.cache_key))

        # The dependency store for this instance should be cleared.
        keys = self.dependency_store.get_cache_keys(
            dummy_get_model_name(self.instance), self.instance.pk
        )
        self.assertEqual(len(keys), 0)


class TestCacheInvalidationForDeleteEvents(unittest.TestCase):
    def setUp(self):
        # Set up a fake Redis client and caching components.
        self.redis_client = fakeredis.FakeStrictRedis()
        self.cache_backend = RedisCacheBackend(self.redis_client)
        self.dependency_store = RedisDependencyStore(self.redis_client)

        # Create our dummy caching helper.
        self.caching = DummyCaching(self.cache_backend, self.dependency_store)

        # Create an emitter that will simulate signal triggering.
        self.emitter = CacheInvalidationEmitter(
            cache_backend=self.cache_backend,
            dependency_store=self.dependency_store,
            get_model_name=dummy_get_model_name,
        )

        # Create a dummy model instance using the actual dummy model.
        self.instance = DummyModel.objects.create(name="TestModelForDelete")
        self.fields_map = {"name": {"name"}}
        self.depth = 0

        # Generate a cache key similar to production.
        key_data = {
            "model": dummy_get_model_name(DummyModel),
            "primary_key": self.instance.pk,
            "depth": self.depth,
            "fields_map": {k: sorted(list(v)) for k, v in self.fields_map.items()},
        }
        key_str = json.dumps(key_data, sort_keys=True)
        self.cache_key = hashlib.md5(key_str.encode("utf-8")).hexdigest()

        # Cache some data for this instance
        self.value = {"result": "data for delete test"}
        self.caching.context["dependency_registry"] = {}
        self.caching.log_dependency(self.instance, dummy_get_model_name)
        self.caching.cache_result(self.cache_key, self.value, ttl=60)

    def tearDown(self):
        # Clean up the dummy instance.
        DummyModel.objects.all().delete()

    def test_delete_signal_invalidation(self):
        """
        Test that cache invalidation correctly occurs when a DELETE signal is emitted.
        """
        # First verify the value is in the cache
        self.assertEqual(self.cache_backend.get(self.cache_key), self.value)

        # Verify that the dependency store has recorded the cache key
        keys = self.dependency_store.get_cache_keys(
            dummy_get_model_name(self.instance), self.instance.pk
        )
        self.assertIn(self.cache_key, keys)

        # Simulate DELETE signal by calling the emitter's emit method
        self.emitter.emit(ActionType.DELETE, self.instance)

        # The cache key should be invalidated
        self.assertIsNone(self.cache_backend.get(self.cache_key))

        # The dependency store should be cleared for this instance
        keys = self.dependency_store.get_cache_keys(
            dummy_get_model_name(self.instance), self.instance.pk
        )
        self.assertEqual(len(keys), 0)

    def test_manual_cache_invalidation(self):
        """
        Test that the manual invalidation method correctly invalidates cache when called.
        """
        # First verify the value is in the cache
        self.assertEqual(self.cache_backend.get(self.cache_key), self.value)

        # Manually invalidate the cache using the caching mixin
        self.caching.invalidate_cache_for_instance(
            self.dependency_store,
            self.cache_backend,
            dummy_get_model_name(self.instance),
            self.instance.pk,
        )

        # The cache key should be invalidated
        self.assertIsNone(self.cache_backend.get(self.cache_key))

        # The dependency store should be cleared for this instance
        keys = self.dependency_store.get_cache_keys(
            dummy_get_model_name(self.instance), self.instance.pk
        )
        self.assertEqual(len(keys), 0)

    def test_instance_deletion_with_query_caching(self):
        """
        Test a scenario simulating instance deletion with query caching.
        This more closely mimics the actual application workflow.
        """
        # Create a second cache key for a query that returns this instance
        query_key = f"query_{self.instance.pk}"
        query_result = {
            "results": [{"id": self.instance.pk, "name": self.instance.name}]
        }

        # Set up dependency for the query result
        self.caching.context["dependency_registry"] = {}
        self.caching.log_dependency(self.instance, dummy_get_model_name)
        self.caching.cache_result(query_key, query_result, ttl=60)

        # Verify both the instance data and query result are cached
        self.assertEqual(self.cache_backend.get(self.cache_key), self.value)
        self.assertEqual(self.cache_backend.get(query_key), query_result)

        # Emit DELETE signal
        self.emitter.emit(ActionType.DELETE, self.instance)

        # Both cache entries should be invalidated
        self.assertIsNone(self.cache_backend.get(self.cache_key))
        self.assertIsNone(self.cache_backend.get(query_key))


if __name__ == "__main__":
    unittest.main()
