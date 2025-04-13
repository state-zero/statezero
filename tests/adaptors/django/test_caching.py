import hashlib
import json
import unittest
from typing import Any, Callable, Dict, Optional, Set, Type

import fakeredis

from statezero.core.caching import (CacheInvalidationEmitter,
                                    RedisCacheBackend, generate_cache_key)
from statezero.core.types import ActionType
# Import your actual dummy model from tests.django_app.models.
from tests.django_app.models import \
    DummyModel  # adjust the import path as needed


class TestRedisCacheBackend(unittest.TestCase):
    """Test the Redis cache backend functionality"""
    
    def setUp(self):
        """Set up a fresh Redis instance for each test"""
        self.redis_client = fakeredis.FakeStrictRedis()
        self.cache_backend = RedisCacheBackend(self.redis_client)
        
        # Add some test data to Redis
        self.redis_client.set("test:key1", b'"value1"')
        self.redis_client.set("test:key2", b'"value2"')
        self.redis_client.set("other:key1", b'"other_value"')
        
    def test_get(self):
        """Test retrieving values from cache"""
        # Test existing key
        self.assertEqual(self.cache_backend.get("test:key1"), "value1")
        
        # Test non-existent key
        self.assertIsNone(self.cache_backend.get("nonexistent:key"))
        
        # Test with invalid JSON
        self.redis_client.set("invalid:json", b'not json')
        self.assertIsNone(self.cache_backend.get("invalid:json"))
        
    def test_set(self):
        """Test setting values in cache"""
        # Test simple value
        self.cache_backend.set("new:key", "new_value")
        self.assertEqual(self.redis_client.get("new:key"), b'"new_value"')
        
        # Test complex value
        complex_data = {"key": "value", "nested": {"a": 1, "b": 2}}
        self.cache_backend.set("complex:key", complex_data)
        self.assertEqual(json.loads(self.redis_client.get("complex:key")), complex_data)
        
        # Test with TTL
        self.cache_backend.set("ttl:key", "ttl_value", ttl=60)
        self.assertEqual(self.redis_client.get("ttl:key"), b'"ttl_value"')
        self.assertGreaterEqual(self.redis_client.ttl("ttl:key"), 0)
        
    def test_invalidate_pattern(self):
        """Test pattern-based invalidation"""
        # Test invalidating by prefix
        self.cache_backend.invalidate_pattern("test:*")
        self.assertIsNone(self.redis_client.get("test:key1"))
        self.assertIsNone(self.redis_client.get("test:key2"))
        self.assertEqual(self.redis_client.get("other:key1"), b'"other_value"')
        
        # Test invalidating specific key pattern
        self.redis_client.set("model:1:abc", b'"data1"')
        self.redis_client.set("model:1:def", b'"data2"')
        self.redis_client.set("model:2:abc", b'"data3"')
        
        self.cache_backend.invalidate_pattern("model:1:*")
        self.assertIsNone(self.redis_client.get("model:1:abc"))
        self.assertIsNone(self.redis_client.get("model:1:def"))
        self.assertEqual(self.redis_client.get("model:2:abc"), b'"data3"')
        
        # Test invalidating non-matching pattern (should do nothing)
        self.cache_backend.invalidate_pattern("nonexistent:*")
        self.assertEqual(self.redis_client.get("model:2:abc"), b'"data3"')


class TestCacheKeyGeneration(unittest.TestCase):
    """Test the cache key generation functionality"""
    
    def test_generate_cache_key_for_instance(self):
        """Test generating a cache key for a specific instance"""
        model_name = "TestModel"
        instance_id = 123
        fields_map = {
            "TestModel": {"id", "name", "description"},
            "RelatedModel": {"id", "title"}
        }
        
        key = generate_cache_key(model_name, instance_id, fields_map)
        
        # Ensure key has the right format
        self.assertTrue(key.startswith(f"{model_name}:{instance_id}:"))
        
        # Ensure consistent hashing
        fields_dict = {k: sorted(list(v)) for k, v in fields_map.items()}
        fields_json = json.dumps(fields_dict, sort_keys=True)
        expected_hash = hashlib.md5(fields_json.encode("utf-8")).hexdigest()
        
        self.assertTrue(key.endswith(expected_hash))
        
    def test_generate_cache_key_for_collection(self):
        """Test generating a cache key for a collection"""
        model_name = "TestModel"
        fields_map = {"TestModel": {"id", "name"}}
        
        key = generate_cache_key(model_name, None, fields_map)
        
        # Ensure key has the right format
        self.assertTrue(key.startswith(f"{model_name}:collection:"))
        
        # Test with empty fields map
        key = generate_cache_key(model_name, None, {})
        self.assertTrue(key.startswith(f"{model_name}:collection:"))
        
    def test_generate_cache_key_consistency(self):
        """Test that the same inputs always generate the same key"""
        model_name = "TestModel"
        instance_id = 456
        fields_map = {"TestModel": {"id", "name"}}
        
        key1 = generate_cache_key(model_name, instance_id, fields_map)
        key2 = generate_cache_key(model_name, instance_id, fields_map)
        
        self.assertEqual(key1, key2)
        
        # Test that different field ordering produces the same key
        fields_map1 = {"TestModel": {"id", "name"}}
        fields_map2 = {"TestModel": {"name", "id"}}
        
        key1 = generate_cache_key(model_name, instance_id, fields_map1)
        key2 = generate_cache_key(model_name, instance_id, fields_map2)
        
        self.assertEqual(key1, key2)


class TestCacheInvalidationEmitter(unittest.TestCase):
    """Test the cache invalidation emitter functionality"""
    
    def setUp(self):
        """Set up the emitter with a mock cache backend"""
        self.redis_client = fakeredis.FakeStrictRedis()
        self.cache_backend = RedisCacheBackend(self.redis_client)
        
        # A simple function to get a model's name
        def get_model_name(model_class):
            return model_class.__name__
            
        self.get_model_name = get_model_name
        self.emitter = CacheInvalidationEmitter(
            cache_backend=self.cache_backend,
            get_model_name=self.get_model_name
        )
        
        # Add some test data to Redis
        self.redis_client.set("DummyModel:1:abc", b'"instance_data"')
        self.redis_client.set("DummyModel:2:abc", b'"instance_data2"')
        self.redis_client.set("DummyModel:collection:abc", b'"collection_data"')
        self.redis_client.set("OtherModel:1:abc", b'"other_data"')
        
    def test_emit_for_instance(self):
        """Test emitting an event for a model instance"""
        # Create a dummy instance
        dummy = DummyModel(pk=1)
        
        # Emit a CREATE event
        self.emitter.emit(ActionType.CREATE, dummy)
        
        # All DummyModel cache entries should be invalidated
        self.assertIsNone(self.redis_client.get("DummyModel:1:abc"))
        self.assertIsNone(self.redis_client.get("DummyModel:2:abc"))
        self.assertIsNone(self.redis_client.get("DummyModel:collection:abc"))
        
        # OtherModel entries should remain
        self.assertEqual(self.redis_client.get("OtherModel:1:abc"), b'"other_data"')
        
    def test_emit_for_pre_event(self):
        """Test that pre-events don't trigger invalidation"""
        dummy = DummyModel(pk=1)
        
        # Emit a PRE_UPDATE event
        self.emitter.emit(ActionType.PRE_UPDATE, dummy)
        
        # No cache entries should be invalidated
        self.assertEqual(self.redis_client.get("DummyModel:1:abc"), b'"instance_data"')
        self.assertEqual(self.redis_client.get("DummyModel:2:abc"), b'"instance_data2"')
        self.assertEqual(self.redis_client.get("DummyModel:collection:abc"), b'"collection_data"')
        
    def test_emit_bulk(self):
        """Test emitting a bulk event"""
        # Create multiple dummy instances
        dummies = [DummyModel(pk=1), DummyModel(pk=2)]
        
        # Emit a BULK_UPDATE event
        self.emitter.emit_bulk(ActionType.BULK_UPDATE, dummies)
        
        # All DummyModel cache entries should be invalidated
        self.assertIsNone(self.redis_client.get("DummyModel:1:abc"))
        self.assertIsNone(self.redis_client.get("DummyModel:2:abc"))
        self.assertIsNone(self.redis_client.get("DummyModel:collection:abc"))
        
        # OtherModel entries should remain
        self.assertEqual(self.redis_client.get("OtherModel:1:abc"), b'"other_data"')
        
    def test_emit_bulk_for_pre_event(self):
        """Test that pre-events don't trigger bulk invalidation"""
        dummies = [DummyModel(pk=1), DummyModel(pk=2)]
        
        # Emit a PRE_UPDATE event
        self.emitter.emit_bulk(ActionType.PRE_DELETE, dummies)
        
        # No cache entries should be invalidated
        self.assertEqual(self.redis_client.get("DummyModel:1:abc"), b'"instance_data"')
        self.assertEqual(self.redis_client.get("DummyModel:2:abc"), b'"instance_data2"')
        self.assertEqual(self.redis_client.get("DummyModel:collection:abc"), b'"collection_data"')
        
    def test_emit_bulk_empty_list(self):
        """Test emitting a bulk event with an empty list"""
        # This should do nothing and not raise any errors
        self.emitter.emit_bulk(ActionType.BULK_UPDATE, [])
        
        # All cache entries should remain
        self.assertEqual(self.redis_client.get("DummyModel:1:abc"), b'"instance_data"')
        self.assertEqual(self.redis_client.get("DummyModel:2:abc"), b'"instance_data2"')
        self.assertEqual(self.redis_client.get("DummyModel:collection:abc"), b'"collection_data"')


if __name__ == "__main__":
    unittest.main()