import hashlib
import json
import logging
import time
from threading import Lock
from typing import Any, Callable, Dict, Optional, Set, Type, List

import orjson

from statezero.core.interfaces import (AbstractCacheBackend,
                                       AbstractDependencyStore,
                                       AbstractEventEmitter)
from statezero.core.types import (ActionType, ORMModel,  # type: ignore
                                  RequestType)

logger = logging.getLogger(__name__)


class RedisCacheBackend(AbstractCacheBackend):
    """Redis-based cache backend that accepts any Redis client implementation"""

    def __init__(self, redis_client, default_ttl: Optional[int] = None):
        self.redis_client = redis_client
        self.default_ttl = default_ttl
        self.lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        """Retrieve and deserialize a value from cache using orjson."""
        with self.lock:
            try:
                data = self.redis_client.get(key)
                if data is None:
                    return None
                # orjson.loads returns a native Python object
                return orjson.loads(data)
            except Exception as e:
                logger.error(f"Error retrieving key {key} from cache: {str(e)}")
                return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Serialize and set a value in cache with an optional TTL using orjson."""
        with self.lock:
            try:
                # orjson.dumps returns bytes directly.
                serialized_value = orjson.dumps(value)
                expiration = ttl or self.default_ttl
                if expiration is not None:
                    self.redis_client.set(key, serialized_value, ex=expiration)
                else:
                    self.redis_client.set(key, serialized_value)
            except Exception as e:
                logger.error(f"Error setting key {key} in cache: {str(e)}")

    def invalidate(self, key: str) -> None:
        """Remove a key from cache."""
        with self.lock:
            try:
                self.redis_client.delete(key)
            except Exception as e:
                logger.error(f"Error invalidating key {key} from cache: {str(e)}")
                
    def invalidate_pattern(self, pattern: str) -> None:
        """Remove all keys matching the given pattern from cache."""
        with self.lock:
            try:
                # Use Redis SCAN command to find keys matching the pattern
                cursor = '0'
                while cursor != 0:
                    cursor, keys = self.redis_client.scan(cursor=cursor, match=pattern, count=100)
                    if keys:
                        self.redis_client.delete(*keys)
                    # Convert string cursor to int for comparison
                    cursor = int(cursor)
            except Exception as e:
                logger.error(f"Error invalidating keys with pattern {pattern}: {str(e)}")
    
    def invalidate_multi_pattern(self, patterns: List[str]) -> None:
        """Remove all keys matching any of the given patterns from cache."""
        with self.lock:
            try:
                all_keys = set()
                for pattern in patterns:
                    cursor = '0'
                    while cursor != 0:
                        cursor, keys = self.redis_client.scan(cursor=cursor, match=pattern, count=100)
                        all_keys.update(keys)
                        # Convert string cursor to int for comparison
                        cursor = int(cursor)
                
                # Delete all keys in batches to avoid too long command
                if all_keys:
                    # Split into batches of 1000 keys each
                    batch_size = 1000
                    for i in range(0, len(all_keys), batch_size):
                        batch = list(all_keys)[i:i+batch_size]
                        if batch:
                            self.redis_client.delete(*batch)
            except Exception as e:
                logger.error(f"Error invalidating multiple patterns: {str(e)}")

def generate_cache_key(
    model: Type[ORMModel],  # type: ignore
    instance: ORMModel,  # type: ignore
    depth: int,
    fields_map: Dict[str, Set[str]],
    get_model_name: Callable[[Type[ORMModel]], str],  # type: ignore
) -> str:
    """
    Generate a cache key with the model name and primary key as a prefix
    to enable pattern-based invalidation.
    """
    model_name = get_model_name(model)
    
    key_data = {
        "depth": depth,
        "fields_map": {k: sorted(list(v)) for k, v in fields_map.items()},
    }
    key_str = json.dumps(key_data, sort_keys=True)
    hash_suffix = hashlib.md5(key_str.encode("utf-8")).hexdigest()
    
    # Format: model_name:pk:hash
    return f"{model_name}:{instance.pk}:{hash_suffix}"

class CachingMixin:
    """
    A simplified mixin to add caching logic to a serializer without dependency tracking.
    
    - `generate_cache_key` uses static properties of the serialization process.
    - `cache_result` stores a computed result in a pluggable cache backend.
    
    The cache backend is expected to be provided by the framework.
    """

    # Pluggable cache backend. For example, an instance wrapping Redis or similar.
    cache_backend: Optional[AbstractCacheBackend] = None

    @classmethod
    def generate_cache_key(
        cls,
        model: Type[ORMModel],  # type: ignore
        instance: ORMModel,  # type: ignore
        depth: int,
        fields_map: Dict[str, Set[str]],
        get_model_name: Callable[[Type[ORMModel]], str],  # type: ignore
    ) -> str:
        return generate_cache_key(model, instance, depth, fields_map, get_model_name)

    def cache_result(
        self, cache_key: str, result: Any, ttl: Optional[int] = None
    ) -> Any:
        """
        Cache the provided result using the generated cache key.
        """
        if self.cache_backend is None:
            raise ValueError("Cache backend is not configured.")

        # Cache the result.
        self.cache_backend.set(cache_key, result, ttl=ttl)
        return result

    def get_cached_result(self, cache_key: str) -> Optional[Any]:
        """
        Retrieve a cached result using the provided cache key, if available.
        """
        if self.cache_backend is None:
            raise ValueError("Cache backend is not configured.")
        return self.cache_backend.get(cache_key)

class CacheInvalidationEmitter(AbstractEventEmitter):
    def __init__(
        self,
        cache_backend: AbstractCacheBackend,
        get_model_name: Callable[[Type[ORMModel]], str],  # type:ignore
    ) -> None:
        """
        Simplified cache invalidation emitter without dependency tracking.
        
        :param cache_backend: The cache backend used to invalidate cache keys.
        :param get_model_name: A function that takes an ORMModel instance and returns its model name.
        """
        self.cache_backend = cache_backend
        self.get_model_name = get_model_name

    def emit(
        self, event_type: ActionType, instance: Type[ORMModel]
    ) -> None:  # type:ignore
        # Use the injected callable to get the model name from the instance
        model_name = self.get_model_name(instance)
        
        # Create a model-specific cache key pattern
        cache_key_pattern = f"{model_name}:{instance.pk}:*"
        
        # Invalidate all cache entries that match the pattern
        self._invalidate_cache_keys_by_pattern(cache_key_pattern)

    def emit_bulk(
        self, event_type: ActionType, instances: List[Type[ORMModel]]
    ) -> None:
        """
        Handle bulk invalidation more efficiently by:
        1. Grouping instances by model type
        2. For each model type, invalidate all instances in a single operation if possible
        """
        if not instances:
            return
            
        # Group instances by model name
        model_groups = {}
        for instance in instances:
            model_name = self.get_model_name(instance)
            if model_name not in model_groups:
                model_groups[model_name] = []
            model_groups[model_name].append(instance.pk)
            
        # Invalidate each model group
        for model_name, pks in model_groups.items():
            if len(pks) == 1:
                # Single instance - use standard pattern
                cache_key_pattern = f"{model_name}:{pks[0]}:*"
                self._invalidate_cache_keys_by_pattern(cache_key_pattern)
            else:
                # Multiple instances - use more efficient method if available
                if hasattr(self.cache_backend, 'invalidate_multi_pattern'):
                    patterns = [f"{model_name}:{pk}:*" for pk in pks]
                    self.cache_backend.invalidate_multi_pattern(patterns)
                else:
                    # Fall back to invalidating one by one
                    for pk in pks:
                        cache_key_pattern = f"{model_name}:{pk}:*"
                        self._invalidate_cache_keys_by_pattern(cache_key_pattern)

    def has_permission(self, request: RequestType, namespace: str) -> bool:
        # Cache invalidation is internal and doesn't require permission checks.
        return True

    def authenticate(self, request: RequestType) -> None:
        # No authentication required for cache invalidation.
        pass
        
    def _invalidate_cache_keys_by_pattern(self, pattern: str) -> None:
        """
        Invalidate all cache keys matching the given pattern.
        """
        try:
            # If your cache backend has a method to delete by pattern, use it
            if hasattr(self.cache_backend, 'invalidate_pattern'):
                self.cache_backend.invalidate_pattern(pattern)
            else:
                # Legacy implementation goes here
                # This would be specific to your cache backend
                logger.warning(f"Cache backend does not support pattern invalidation: {pattern}")
        except Exception as e:
            logger.exception(f"Error invalidating cache keys with pattern {pattern}: {str(e)}")