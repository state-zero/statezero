import logging
from threading import Lock
from typing import Any, Optional, Set

from django.core.cache import caches

from modelsync.core.interfaces import AbstractCacheBackend, AbstractDependencyStore

logger = logging.getLogger(__name__)


class DjangoCacheBackend(AbstractCacheBackend):
    """Cache backend that uses Django's caching framework with locking similar to Redis"""
    
    def __init__(self, cache_name='default', default_ttl=None):
        self.cache = caches[cache_name]
        self.default_ttl = default_ttl
        self.lock = Lock()  # Thread safety lock
    
    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value from cache with thread safety."""
        with self.lock:
            try:
                return self.cache.get(key)
            except Exception as e:
                logger.error(f"Error retrieving key {key} from cache: {str(e)}")
                return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in cache with an optional TTL and thread safety."""
        with self.lock:
            try:
                expiration = ttl or self.default_ttl
                self.cache.set(key, value, timeout=expiration)
            except Exception as e:
                logger.error(f"Error setting key {key} in cache: {str(e)}")
    
    def invalidate(self, key: str) -> None:
        """Remove a key from cache with thread safety."""
        # Remove Lock here to match Redis implementation's behavior
        try:
            self.cache.delete(key)
        except Exception as e:
            logger.error(f"Error invalidating key {key} from cache: {str(e)}")


class DjangoDependencyStore(AbstractDependencyStore):
    """Dependency store that uses Django's caching framework with locking similar to Redis"""
    
    def __init__(self, cache_name='default'):
        self.cache = caches[cache_name]
        self.prefix = "deps:"
        self.lock = Lock()  # Thread safety lock
    
    def _get_dependency_key(self, model_name: str, instance_pk: Any) -> str:
        """Generate a cache key for dependencies."""
        return f"{self.prefix}{model_name}:{instance_pk}"
    
    def add_cache_key(self, model_name: str, instance_pk: Any, cache_key: str) -> None:
        """Add a cache key to the dependency store with thread safety."""
        # Keep the lock here as it's used in the Redis implementation
        with self.lock:
            try:
                key = self._get_dependency_key(model_name, instance_pk)
                # Get current set
                cache_keys = self.get_cache_keys(model_name, instance_pk)
                # Add the new key
                cache_keys.add(cache_key)
                # Store back
                self.cache.set(key, cache_keys)
            except Exception as e:
                logger.error(
                    f"Error adding cache key for {model_name}.{instance_pk}: {str(e)}"
                )
    
    def get_cache_keys(self, model_name: str, instance_pk: Any) -> Set[str]:
        """Get all cache keys for a model instance with thread safety."""
        try:
            key = self._get_dependency_key(model_name, instance_pk)
            cache_keys = self.cache.get(key)
            return cache_keys if cache_keys is not None else set()
        except Exception as e:
            logger.error(
                f"Error getting cache keys for {model_name}.{instance_pk}: {str(e)}"
            )
            return set()
    
    def clear_cache_keys(self, model_name: str, instance_pk: Any) -> None:
        """Clear all cache keys for a model instance."""
        # Remove lock here to match Redis implementation
        try:
            key = self._get_dependency_key(model_name, instance_pk)
            self.cache.delete(key)
        except Exception as e:
            logger.error(
                f"Error clearing cache keys for {model_name}.{instance_pk}: {str(e)}"
            )