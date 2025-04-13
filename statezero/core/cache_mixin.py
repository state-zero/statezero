import logging
from typing import Any, Dict, Optional, Set, Type, TypeVar, Callable, Tuple
from django.db import models

from statezero.core.caching import generate_cache_key
from statezero.core.interfaces import AbstractCacheBackend
from statezero.core.types import RequestType

logger = logging.getLogger(__name__)

T = TypeVar('T')

def try_cache_serialization(
    data: Any,
    model: Type[models.Model],
    fields_map: Dict[str, Set[str]],
    cache_backend: AbstractCacheBackend,
    get_model_name: Callable[[Type], str],
    many: bool = False
) -> Tuple[bool, Optional[Any], Optional[str]]:
    """
    Helper function to try retrieving serialized data from cache.
    
    Args:
        data: The model instance or queryset to serialize
        model: The model class
        fields_map: The fields map defining what to include
        cache_backend: The cache backend to use
        get_model_name: Function to get a model's name
        many: Whether we're serializing multiple instances
        
    Returns:
        Tuple of (success, result, cache_key)
        - success: Boolean indicating if cache was successful
        - result: The cached result or None if not found
        - cache_key: The generated cache key or None if not applicable
    """
    # Skip if no data or no cache backend
    if data is None or cache_backend is None:
        return False, None, None
    
    # We only cache single instance serialization
    if many or not isinstance(data, model):
        return False, None, None
    
    try:
        # Get model name
        model_name = get_model_name(model)
        # Get instance ID
        instance_id = getattr(data, data._meta.pk.name)
        
        # Generate cache key for the entire serialized result
        cache_key = generate_cache_key(
            model_name=model_name,
            instance_id=instance_id,
            fields_map=fields_map
        )
        
        # Try to get from cache
        cached_result = cache_backend.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Cache hit for serialization {cache_key}")
            return True, cached_result, cache_key
            
        logger.debug(f"Cache miss for serialization {cache_key}")
        return False, None, cache_key
    except Exception as e:
        logger.warning(f"Error attempting to use serialization cache: {e}")
        return False, None, None


def cache_serialization_result(
    result: Any,
    cache_key: str,
    cache_backend: AbstractCacheBackend,
    ttl: Optional[int] = None
) -> None:
    """
    Helper function to cache serialization result.
    
    Args:
        result: The serialization result to cache
        cache_key: The cache key to use
        cache_backend: The cache backend to use
        ttl: Optional TTL override
    """
    if not cache_key or not cache_backend:
        return
        
    try:
        cache_backend.set(cache_key, result, ttl=ttl)
        logger.debug(f"Cached serialization result with key {cache_key}")
    except Exception as e:
        logger.warning(f"Error caching serialization result: {e}")


class CacheableSerializerMixin:
    """
    Mixin that adds caching capabilities to serializers.
    
    This mixin provides methods for caching serialized results.
    """
    
    def try_cache(
        self,
        data: Any,
        model: Type[models.Model],
        fields_map: Dict[str, Set[str]],
        get_model_name: Callable[[Type], str],
        many: bool = False
    ) -> Tuple[bool, Optional[Any], Optional[str]]:
        """
        Try to get serialized data from cache.
        
        Args:
            data: The model instance or queryset to serialize
            model: The model class
            fields_map: The fields map defining what to include
            get_model_name: Function to get a model's name
            many: Whether we're serializing multiple instances
            
        Returns:
            Tuple of (success, result, cache_key)
        """
        if not hasattr(self, 'cache_backend') or not self.cache_backend:
            return False, None, None
            
        return try_cache_serialization(
            data=data,
            model=model,
            fields_map=fields_map,
            cache_backend=self.cache_backend,
            get_model_name=get_model_name,
            many=many
        )
        
    def cache_result(
        self,
        result: Any,
        cache_key: str,
        ttl: Optional[int] = None
    ) -> None:
        """
        Cache serialization result.
        
        Args:
            result: The serialization result to cache
            cache_key: The cache key to use
            ttl: Optional TTL override
        """
        if not hasattr(self, 'cache_backend') or not self.cache_backend:
            return
            
        cache_serialization_result(
            result=result,
            cache_key=cache_key,
            cache_backend=self.cache_backend,
            ttl=ttl
        )