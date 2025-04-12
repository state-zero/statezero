import hashlib
import json
import unittest
from typing import Any, Callable, Dict, Optional, Set, Type

import fakeredis

from statezero.core.caching import (CacheInvalidationEmitter, CachingMixin,
                                    RedisCacheBackend, generate_cache_key)
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
    def __init__(self, cache_backend):
        self.cache_backend = cache_backend


class TestCacheInvalidation(unittest.TestCase):
    def setUp(self):
        # Set up a fake Redis client and caching components.
        self.redis_client = fakeredis.FakeStrictRedis()
        self.cache_backend = RedisCacheBackend(self.redis_client)
        
        # Create our dummy caching helper.
        self.caching = DummyCaching(self.cache_backend)
        
        # Create an emitter that will simulate signal triggering.
        self.emitter = CacheInvalidationEmitter(
            cache_backend=self.cache_backend,
            get_model_name=dummy_get_model_name,
        )
        
        # Create a dummy model instance using the actual dummy model.
        self.instance = DummyModel.objects.create(name="TestModel")
        self.fields_map = {"name": {"name"}}
        self.depth = 0

        # Generate a cache key using the new format
        self.model_name = dummy_get_model_name(DummyModel)
        key_data = {
            "depth": self.depth,
            "fields_map": {k: sorted(list(v)) for k, v in self.fields_map.items()},
        }
        key_str = json.dumps(key_data, sort_keys=True)
        hash_suffix = hashlib.md5(key_str.encode("utf-8")).hexdigest()
        self.cache_key = f"{self.model_name}:{self.instance.pk}:{hash_suffix}"

    def tearDown(self):
        # Clean up the dummy instance.
        DummyModel.objects.all().delete()

    def test_cache_set_and_get(self):
        """Ensure that a value can be set and retrieved from the cache."""
        value = {"result": "data"}
        # Cache the result.
        self.caching.cache_result(self.cache_key, value, ttl=60)

        # Retrieve value from cache.
        cached_value = self.cache_backend.get(self.cache_key)
        self.assertEqual(cached_value, value)

    def test_signal_based_invalidation(self):
        """
        Simulate a Django signal (such as post_save) by calling the emitter's emit method,
        and verify that the cache key is invalidated.
        """
        value = {"result": "data"}
        self.caching.cache_result(self.cache_key, value, ttl=60)

        # Verify that the key is in the cache.
        self.assertEqual(self.cache_backend.get(self.cache_key), value)

        # Now simulate triggering the invalidation signal.
        self.emitter.emit(ActionType.UPDATE, self.instance)

        # The cache key should be invalidated.
        self.assertIsNone(self.cache_backend.get(self.cache_key))

    def test_pattern_based_invalidation(self):
        """Test that pattern-based invalidation works correctly."""
        # Create several cache keys with the same model and instance but different hashes
        value1 = {"result": "data1"}
        value2 = {"result": "data2"}
        value3 = {"result": "data3"}
        
        # Manually create keys with different hash suffixes
        key1 = f"{self.model_name}:{self.instance.pk}:hash1"
        key2 = f"{self.model_name}:{self.instance.pk}:hash2"
        key3 = f"{self.model_name}:{self.instance.pk}:hash3"
        
        # A key for a different instance
        other_instance = DummyModel.objects.create(name="OtherModel")
        other_key = f"{self.model_name}:{other_instance.pk}:hash1"
        
        # Set all the values
        self.cache_backend.set(key1, value1)
        self.cache_backend.set(key2, value2)
        self.cache_backend.set(key3, value3)
        self.cache_backend.set(other_key, value1)
        
        # Verify all values are in the cache
        self.assertEqual(self.cache_backend.get(key1), value1)
        self.assertEqual(self.cache_backend.get(key2), value2)
        self.assertEqual(self.cache_backend.get(key3), value3)
        self.assertEqual(self.cache_backend.get(other_key), value1)
        
        # Simulate an update to the first instance
        pattern = f"{self.model_name}:{self.instance.pk}:*"
        self.cache_backend.invalidate_pattern(pattern)
        
        # Check that all keys for the first instance are invalidated
        self.assertIsNone(self.cache_backend.get(key1))
        self.assertIsNone(self.cache_backend.get(key2))
        self.assertIsNone(self.cache_backend.get(key3))
        
        # But the key for the other instance should still be there
        self.assertEqual(self.cache_backend.get(other_key), value1)


class TestBulkCacheInvalidation(unittest.TestCase):
    def setUp(self):
        # Set up a fake Redis client and caching components.
        self.redis_client = fakeredis.FakeStrictRedis()
        self.cache_backend = RedisCacheBackend(self.redis_client)
        
        # Create our dummy caching helper.
        self.caching = DummyCaching(self.cache_backend)
        
        # Create an emitter that will simulate signal triggering.
        self.emitter = CacheInvalidationEmitter(
            cache_backend=self.cache_backend,
            get_model_name=dummy_get_model_name,
        )
        
        # Create multiple dummy model instances
        self.instances = [
            DummyModel.objects.create(name=f"TestModel{i}") 
            for i in range(3)
        ]
        
        self.model_name = dummy_get_model_name(DummyModel)
        self.fields_map = {"name": {"name"}}
        self.depth = 0
        
        # Generate cache keys for each instance
        self.cache_keys = []
        for instance in self.instances:
            key_data = {
                "depth": self.depth,
                "fields_map": {k: sorted(list(v)) for k, v in self.fields_map.items()},
            }
            key_str = json.dumps(key_data, sort_keys=True)
            hash_suffix = hashlib.md5(key_str.encode("utf-8")).hexdigest()
            self.cache_keys.append(f"{self.model_name}:{instance.pk}:{hash_suffix}")

    def tearDown(self):
        # Clean up the dummy instances.
        DummyModel.objects.all().delete()

    def test_bulk_invalidation(self):
        """Test that bulk invalidation correctly invalidates multiple cache keys."""
        # Set values for all cache keys
        for i, key in enumerate(self.cache_keys):
            value = {"result": f"data{i}"}
            self.caching.cache_result(key, value, ttl=60)
            
        # Verify all values are in the cache
        for i, key in enumerate(self.cache_keys):
            self.assertEqual(self.cache_backend.get(key), {"result": f"data{i}"})
            
        # Simulate bulk invalidation
        self.emitter.emit_bulk(ActionType.BULK_UPDATE, self.instances)
        
        # Check that all keys are invalidated
        for key in self.cache_keys:
            self.assertIsNone(self.cache_backend.get(key))
            
    def test_multi_pattern_invalidation(self):
        """Test that multi_pattern invalidation works correctly."""
        # Set values for all cache keys
        for i, key in enumerate(self.cache_keys):
            value = {"result": f"data{i}"}
            self.caching.cache_result(key, value, ttl=60)
            
        # Create patterns for each instance
        patterns = [f"{self.model_name}:{instance.pk}:*" for instance in self.instances]
        
        # Invalidate using multiple patterns
        self.cache_backend.invalidate_multi_pattern(patterns)
        
        # Check that all keys are invalidated
        for key in self.cache_keys:
            self.assertIsNone(self.cache_backend.get(key))


class TestGenerateCacheKey(unittest.TestCase):
    def setUp(self):
        # Create a dummy model instance using the actual dummy model.
        self.instance = DummyModel.objects.create(name="TestModel")
        self.fields_map = {"name": {"name"}}
        self.depth = 0

    def tearDown(self):
        # Clean up the dummy instance.
        DummyModel.objects.all().delete()

    def test_generate_cache_key(self):
        """Test that the generate_cache_key function produces correctly formatted keys."""
        # Generate a cache key using the function
        key = generate_cache_key(
            model=DummyModel,
            instance=self.instance,
            depth=self.depth,
            fields_map=self.fields_map,
            get_model_name=dummy_get_model_name
        )
        
        # Verify the key format starts with model_name:pk:
        model_name = dummy_get_model_name(DummyModel)
        self.assertTrue(key.startswith(f"{model_name}:{self.instance.pk}:"))
        
        # Key should have three parts separated by colons
        parts = key.split(":")
        self.assertEqual(len(parts), 3)


if __name__ == "__main__":
    unittest.main()