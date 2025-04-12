import logging
import re
from threading import Lock
from typing import Any, List, Optional, Set

from django.core.cache import caches

from statezero.core.interfaces import AbstractCacheBackend

logger = logging.getLogger(__name__)

class DjangoCacheBackend(AbstractCacheBackend):
    """Cache backend that uses Django's caching framework with pattern-based invalidation support"""
    
    def __init__(self, cache_name='default', default_ttl=None):
        self.cache = caches[cache_name]
        self.default_ttl = default_ttl
        self.lock = Lock()  # Thread safety lock
        self.key_registry_name = "_cache_key_registry"  # Used for pattern matching
    
    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value from cache with thread safety."""
        with self.lock:
            try:
                return self.cache.get(key)
            except Exception as e:
                logger.error(f"Error retrieving key {key} from cache: {str(e)}")
                return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set a value in cache with an optional TTL and thread safety.
        Also registers the key for pattern matching.
        """
        with self.lock:
            try:
                expiration = ttl or self.default_ttl
                self.cache.set(key, value, timeout=expiration)
                
                # Register this key for pattern matching
                self._register_key(key)
            except Exception as e:
                logger.error(f"Error setting key {key} in cache: {str(e)}")
    
    def invalidate(self, key: str) -> None:
        """Remove a key from cache and unregister it."""
        try:
            self.cache.delete(key)
            self._unregister_key(key)
        except Exception as e:
            logger.error(f"Error invalidating key {key} from cache: {str(e)}")
    
    def invalidate_pattern(self, pattern: str) -> None:
        """
        Remove all keys matching the given pattern from cache.
        Django's cache doesn't support pattern-based operations natively,
        so we implement it using a registry of keys.
        """
        try:
            # Convert Redis-style pattern (with *) to Python regex
            regex_pattern = pattern.replace("*", ".*")
            compiled_pattern = re.compile(regex_pattern)
            
            # Get all registered keys
            all_keys = self._get_registered_keys()
            
            # Find matching keys
            matching_keys = [key for key in all_keys if compiled_pattern.match(key)]
            
            # Delete matching keys
            for key in matching_keys:
                self.invalidate(key)
                
            logger.debug(f"Invalidated {len(matching_keys)} keys matching pattern {pattern}")
        except Exception as e:
            logger.error(f"Error invalidating keys with pattern {pattern}: {str(e)}")
    
    def invalidate_multi_pattern(self, patterns: List[str]) -> None:
        """Remove all keys matching any of the given patterns from cache."""
        try:
            # Convert Redis-style patterns to Python regex
            compiled_patterns = [re.compile(pattern.replace("*", ".*")) for pattern in patterns]
            
            # Get all registered keys
            all_keys = self._get_registered_keys()
            
            # Find matching keys for any pattern
            matching_keys = set()
            for key in all_keys:
                for pattern in compiled_patterns:
                    if pattern.match(key):
                        matching_keys.add(key)
                        break
            
            # Delete matching keys
            for key in matching_keys:
                self.invalidate(key)
                
            logger.debug(f"Invalidated {len(matching_keys)} keys matching multiple patterns")
        except Exception as e:
            logger.error(f"Error invalidating multiple patterns: {str(e)}")
    
    def _register_key(self, key: str) -> None:
        """Register a key in the registry for pattern matching."""
        with self.lock:
            try:
                registry = self.cache.get(self.key_registry_name) or set()
                registry.add(key)
                self.cache.set(self.key_registry_name, registry)
            except Exception as e:
                logger.error(f"Error registering key {key}: {str(e)}")
    
    def _unregister_key(self, key: str) -> None:
        """Remove a key from the registry."""
        with self.lock:
            try:
                registry = self.cache.get(self.key_registry_name) or set()
                if key in registry:
                    registry.remove(key)
                    self.cache.set(self.key_registry_name, registry)
            except Exception as e:
                logger.error(f"Error unregistering key {key}: {str(e)}")
    
    def _get_registered_keys(self) -> Set[str]:
        """Get all registered keys."""
        with self.lock:
            return self.cache.get(self.key_registry_name) or set()