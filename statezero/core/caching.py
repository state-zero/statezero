# statezero/core/caching.py

import hashlib
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Type

import orjson

from statezero.core.interfaces import AbstractCacheBackend, AbstractEventEmitter
from statezero.core.types import ActionType

logger = logging.getLogger(__name__)


class RedisCacheBackend(AbstractCacheBackend):
    """Redis-based cache backend with pattern matching support"""

    def __init__(self, redis_client, default_ttl: Optional[int] = None):
        self.redis_client = redis_client
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """Retrieve and deserialize a value from cache using orjson"""
        try:
            data = self.redis_client.get(key)
            if data is None:
                return None
            return orjson.loads(data)
        except Exception as e:
            logger.error(f"Error retrieving key {key} from cache: {str(e)}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Serialize and set a value in cache with an optional TTL using orjson"""
        try:
            serialized_value = orjson.dumps(value)
            expiration = ttl or self.default_ttl
            if expiration is not None:
                self.redis_client.set(key, serialized_value, ex=expiration)
            else:
                self.redis_client.set(key, serialized_value)
        except Exception as e:
            logger.error(f"Error setting key {key} in cache: {str(e)}")
    
    def invalidate_pattern(self, pattern: str) -> None:
        """
        Invalidate all keys matching the given pattern.
        
        This is the primary method used for model-based invalidation.
        
        Args:
            pattern: Redis pattern to match (e.g., "ModelName:*")
        """
        try:
            # Use Redis' SCAN command to find matching keys
            cursor = '0'
            deleted_count = 0
            
            while cursor != 0:
                cursor, keys = self.redis_client.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    if keys:
                        self.redis_client.delete(*keys)
                        deleted_count += len(keys)
                
                # Convert cursor from bytes to string if needed
                if isinstance(cursor, bytes):
                    cursor = cursor.decode('utf-8')
                
                # Convert to int for comparison
                cursor = int(cursor)
            
            if deleted_count > 0:
                logger.debug(f"Invalidated {deleted_count} keys matching pattern '{pattern}'")
                
        except Exception as e:
            logger.error(f"Error using Redis pattern invalidation for '{pattern}': {str(e)}")


def generate_cache_key(
    model_name: str,
    instance_id: Any,
    fields_map: Dict[str, Set[str]],
) -> str:
    """
    Generate a cache key for model data with a specific fields map.
    
    Format: "ModelName:id|collection:fields_hash"
    
    Args:
        model_name: The name of the model
        instance_id: The ID of the instance or None/special identifier for collections
        fields_map: The fields map defining what to include
        
    Returns:
        A cache key string
    """
    # Convert the fields map to a deterministic string for hashing
    fields_dict = {k: sorted(list(v)) for k, v in fields_map.items() if v}
    fields_json = json.dumps(fields_dict, sort_keys=True)
    fields_hash = hashlib.md5(fields_json.encode("utf-8")).hexdigest()
    
    # Decide if this is for a specific instance or a collection
    if instance_id is None:
        return f"{model_name}:collection:{fields_hash}"
    else:
        # For a specific instance
        return f"{model_name}:{instance_id}:{fields_hash}"


class CacheInvalidationEmitter(AbstractEventEmitter):
    """
    Event emitter that invalidates cache entries when models are modified.
    
    This emitter uses pattern-based invalidation to invalidate ALL cached
    data related to a model when any instance of that model changes.
    """
    
    def __init__(
        self,
        cache_backend: AbstractCacheBackend,
        get_model_name: Callable[[Type], str],
    ) -> None:
        """
        Initialize the cache invalidation emitter.
        
        Args:
            cache_backend: The cache backend to use for invalidation
            get_model_name: Function to get a model's name from its class
        """
        self.cache_backend = cache_backend
        self.get_model_name = get_model_name

    def emit(self, event_type: ActionType, instance: Any) -> None:
        """
        Handle model instance events by invalidating ALL related cache entries.
        
        This method invalidates ALL cached data for a model whenever any
        instance of that model changes, regardless of the specific instance
        or fields map used.
        
        Args:
            event_type: The type of event (CREATE, UPDATE, DELETE, etc.)
            instance: The model instance that triggered the event
        """
        try:
            # Skip pre-operation events
            if event_type in (ActionType.PRE_DELETE, ActionType.PRE_UPDATE):
                return
                
            # Get the model name
            model_class = instance.__class__
            model_name = self.get_model_name(model_class)
            
            # Invalidate ALL cache entries for this model
            # This will match both collections and specific instances
            model_pattern = f"{model_name}:*"
            self.cache_backend.invalidate_pattern(model_pattern)
            
            logger.debug(f"All cache entries invalidated for model {model_name} after {event_type}")
            
        except Exception as e:
            logger.exception(f"Error invalidating cache for {event_type}: {e}")

    def emit_bulk(self, event_type: ActionType, instances: List[Any]) -> None:
        """
        Handle bulk model events by invalidating ALL related cache entries.
        
        For bulk operations, we invalidate all cache entries for the model.
        
        Args:
            event_type: The type of bulk event
            instances: List of model instances that triggered the event
        """
        if not instances:
            return
            
        try:
            # Skip pre-operation events
            if event_type in (ActionType.PRE_DELETE, ActionType.PRE_UPDATE):
                return
                
            # Get model information from the first instance
            first_instance = instances[0]
            model_class = first_instance.__class__
            model_name = self.get_model_name(model_class)
            
            # Invalidate ALL cache entries for this model
            model_pattern = f"{model_name}:*"
            self.cache_backend.invalidate_pattern(model_pattern)
            
            logger.debug(f"Bulk cache invalidation for model {model_name} after {event_type}")
            
        except Exception as e:
            logger.exception(f"Error in bulk cache invalidation for {event_type}: {e}")

    # Required interface methods
    def has_permission(self, request, namespace: str) -> bool:
        """Cache invalidation is always permitted"""
        return True

    def authenticate(self, request) -> None:
        """No authentication required for cache invalidation"""
        pass