import hashlib
import json
import logging
import time
from threading import Lock
from typing import Any, Callable, Dict, Optional, Set, Type, List

import orjson

from ormbridge.core.interfaces import (AbstractCacheBackend,
                                       AbstractDependencyStore,
                                       AbstractEventEmitter)
from ormbridge.core.types import (ActionType, ORMModel,  # type: ignore
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


class RedisDependencyStore(AbstractDependencyStore):
    """Redis-based dependency store that accepts any Redis client implementation"""

    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.lock = Lock()

    def _get_dependency_key(self, model_name: str, instance_pk: Any) -> str:
        """Generate Redis key for dependencies."""
        return f"deps:{model_name}:{instance_pk}"

    def add_cache_key(self, model_name: str, instance_pk: Any, cache_key: str) -> None:
        """Add a cache key to the dependency store."""
        with self.lock:
            try:
                key = self._get_dependency_key(model_name, instance_pk)
                self.redis_client.sadd(key, cache_key)
            except Exception as e:
                logger.error(
                    f"Error adding cache key for {model_name}.{instance_pk}: {str(e)}"
                )

    def get_cache_keys(self, model_name: str, instance_pk: Any) -> Set[str]:
        """Get all cache keys for a model instance."""
        with self.lock:
            try:
                key = self._get_dependency_key(model_name, instance_pk)
                members = self.redis_client.smembers(key)
                return {m.decode("utf-8") for m in members}
            except Exception as e:
                logger.error(
                    f"Error getting cache keys for {model_name}.{instance_pk}: {str(e)}"
                )
                return set()

    def clear_cache_keys(self, model_name: str, instance_pk: Any) -> None:
        """Clear all cache keys for a model instance."""
        with self.lock:
            try:
                key = self._get_dependency_key(model_name, instance_pk)
                self.redis_client.delete(key)
            except Exception as e:
                logger.error(
                    f"Error clearing cache keys for {model_name}.{instance_pk}: {str(e)}"
                )


def generate_cache_key(
    model: Type[ORMModel],  # type: ignore
    instance: ORMModel,  # type: ignore
    depth: int,
    fields_map: Dict[str, Set[str]],
    get_model_name: Callable[[Type[ORMModel]], str],  # type: ignore
) -> str:
    key_data = {
        "model": get_model_name(model),
        "primary_key": instance.pk,
        "depth": depth,
        "fields_map": {k: sorted(list(v)) for k, v in fields_map.items()},
    }
    key_str = json.dumps(key_data, sort_keys=True)
    print(f"DEBUG: key data {json.dumps(key_data)}")
    return hashlib.md5(key_str.encode("utf-8")).hexdigest()

class CachingMixin:
    """
    A mixin to add caching and dependency logging logic to a serializer.

    - `generate_cache_key` uses static properties of the serialization process.
    - `log_dependency` records dependency information (model name and primary key)
      in the serializer's context.
    - `cache_result` stores a computed result in a pluggable cache backend and
      registers its dependencies with a pluggable dependency store.

    Both the cache backend and dependency store are expected to be provided
    by the framework. The cache backend should implement at least `get` and `set`
    methods, while the dependency store should implement an `add_cache_key(model_name, instance_pk, cache_key)`
    method for tracking dependencies.
    """

    # Pluggable cache backend. For example, an instance wrapping Redis or similar.
    cache_backend: Optional[AbstractCacheBackend] = None

    # Pluggable dependency store. It must implement an `add_cache_key` method.
    dependency_store: Optional[AbstractDependencyStore] = None

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

    def log_dependency(
        self, instance: ORMModel, get_model_name: Callable[[Type[ORMModel]], str]  # type: ignore
    ) -> None:  # type: ignore
        """
        Log a dependency for a nested object into the serializer's context.
        Dependencies are stored in a registry under the 'dependency_registry' key,
        mapping model names to sets of instance primary keys.
        """
        # Ensure the registry exists in the context.
        registry: Dict[str, Set[Any]] = self.context.setdefault(
            "dependency_registry", {}
        )
        model_name = get_model_name(instance)
        registry.setdefault(model_name, set()).add(instance.pk)

    def cache_result(
        self, cache_key: str, result: Any, ttl: Optional[int] = None
    ) -> Any:
        """
        Cache the provided result using the generated cache key and record its dependencies.

        Steps:
          1. Store the result in the pluggable cache backend.
          2. Register the cache key with all dependencies logged in the serializer context.
        """
        if self.cache_backend is None:
            raise ValueError("Cache backend is not configured.")

        # Cache the result.
        self.cache_backend.set(cache_key, result, ttl=ttl)

        # Register this cache key for later invalidation based on dependencies.
        self._register_cache_dependencies(cache_key)
        return result

    def _register_cache_dependencies(self, cache_key: str) -> None:
        """
        Associate the given cache key with its dependencies as recorded in the context.
        This method assumes that `log_dependency` has populated the `dependency_registry`
        in `self.context`.
        """
        if self.dependency_store is None:
            # No dependency store is configured; skip dependency registration.
            return

        # dependency_registry maps model names to sets of instance primary keys.
        dependency_registry: Dict[str, Set[Any]] = self.context.get(
            "dependency_registry", {}
        )
        for model_name, instance_pks in dependency_registry.items():
            for instance_pk in instance_pks:
                self.dependency_store.add_cache_key(model_name, instance_pk, cache_key)

    def get_cached_result(self, cache_key: str) -> Optional[Any]:
        """
        Retrieve a cached result using the provided cache key, if available.
        """
        if self.cache_backend is None:
            raise ValueError("Cache backend is not configured.")
        return self.cache_backend.get(cache_key)

    def invalidate_cache_for_instance(
        self,
        dependency_store: AbstractDependencyStore,
        cache_backend: AbstractCacheBackend,
        model_name: str,
        instance_pk: Any,
    ) -> None:
        """
        Given a model name and primary key, look up all associated cache keys and
        invalidate them in the cache backend.
        """
        cache_keys = self.dependency_store.get_cache_keys(model_name, instance_pk)
        for key in cache_keys:
            self.cache_backend.invalidate(key)
        self.dependency_store.clear_cache_keys(model_name, instance_pk)


class CacheInvalidationEmitter(AbstractEventEmitter):
    def __init__(
        self,
        cache_backend: AbstractCacheBackend,
        dependency_store: AbstractDependencyStore,
        get_model_name: Callable[[Type[ORMModel]], str],  # type:ignore
    ) -> None:
        """
        :param cache_backend: The cache backend used to invalidate cache keys.
        :param dependency_store: The dependency store tracking cache keys.
        :param get_model_name: A function that takes an ORMModel instance and returns its model name.
        """
        self.cache_backend = cache_backend
        self.dependency_store = dependency_store
        self.get_model_name = get_model_name

    def emit(
        self, event_type: ActionType, instance: Type[ORMModel]
    ) -> None:  # type:ignore
        # Use the injected callable to get the model name from the instance.
        model_name = self.get_model_name(instance)
        cache_keys = self.dependency_store.get_cache_keys(model_name, instance.pk)
        for key in cache_keys:
            self.cache_backend.invalidate(key)
        self.dependency_store.clear_cache_keys(model_name, instance.pk)

    def emit_bulk(
        self, event_type: ActionType, instances: List[Type[ORMModel]]
    ) -> None:
        # Just loop through all instances and call emit for each one
        for instance in instances:
            self.emit(event_type, instance)

    def has_permission(self, request: RequestType, namespace: str) -> bool:
        # Cache invalidation is internal and doesn't require permission checks.
        return True

    def authenticate(self, request: RequestType) -> None:
        # No authentication required for cache invalidation.
        pass
