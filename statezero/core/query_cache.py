"""
Query-level caching for writes only (push-based approach).

Caches the FINAL serialized response, keyed by:
- SQL query string (which includes permission filters)
- Query parameters
- Transaction ID (canonical_id)

This provides:
1. Automatic permission safety - permissions are in the SQL
2. Zero invalidation logic - new transaction ID = new cache namespace
3. Write path for push-based updates via Pusher
4. Works for both reads and aggregates

Note: Read path has been disabled - cache lookups always return None.
Results are pushed to clients via Pusher instead of being read from cache.
"""
import hashlib
import logging
from typing import Any, Dict, Optional, Tuple

from django.core.cache import cache

from statezero.core.context_storage import current_canonical_id
from statezero.core.telemetry import get_telemetry_context

logger = logging.getLogger(__name__)


def _get_sql_from_queryset(queryset) -> Optional[Tuple[str, tuple]]:
    """
    Extract SQL and params from a Django QuerySet.

    Returns:
        Tuple of (sql, params) or None if compilation fails
    """
    try:
        query = queryset.query
        compiler_obj = query.get_compiler(using=queryset.db)
        sql, params = compiler_obj.as_sql()
        return (sql, params)
    except Exception as e:
        logger.debug(f"Could not compile SQL: {e}")
        return None


def _get_cache_key(sql: str, params: tuple, txn_id: str, operation_context: Optional[str] = None) -> str:
    """
    Generate cache key from SQL + params + transaction ID + operation context.

    Args:
        sql: The compiled SQL query string
        params: Query parameters tuple
        txn_id: Transaction ID (canonical_id)
        operation_context: Optional context string (e.g., "min:value", "max:value")
                          Used to differentiate aggregate operations on same queryset

    Returns:
        Cache key string
    """
    # Normalize params to string
    params_str = str(params) if params else ""

    # Include operation context if provided
    context_str = f":{operation_context}" if operation_context else ""

    # Create deterministic hash
    cache_key_data = f"{sql}:{params_str}:{txn_id}{context_str}"
    hash_digest = hashlib.sha256(cache_key_data.encode()).hexdigest()

    return f"statezero:query:{hash_digest}"


def get_cached_query_result(queryset, operation_context: Optional[str] = None, dry_run: bool = False) -> Optional[Dict[str, Any]]:
    """
    Get cached result for a queryset, or generate cache key in dry-run mode.

    In normal mode: Always returns None (read path disabled for push-based approach).
    In dry-run mode: Returns a dict with the cache key for subscription/polling.

    Args:
        queryset: Django QuerySet to check cache for
        operation_context: Optional context string (e.g., "min:value", "max:value", "read:fields=...")
                          Used to differentiate aggregate operations on same queryset
        dry_run: If True, return cache key instead of executing query (for subscription endpoint)

    Returns:
        Normal mode: Always returns None (read path disabled)
        Dry-run mode: Dict with cache_key or None if cache key cannot be generated
    """
    if dry_run:
        # In dry-run mode, generate and return the cache key
        cache_key = generate_cache_key(queryset, operation_context)
        if cache_key:
            return {
                "cache_key": cache_key,
                "metadata": {"dry_run": True},
            }
        return None

    # Normal mode: read path disabled
    logger.debug("get_cached_query_result called but read path is disabled (push-based approach)")
    return None


def generate_cache_key(queryset, operation_context: Optional[str] = None) -> Optional[str]:
    """
    Generate a cache key for a queryset without executing or caching it.

    This is used for the subscription/polling system where we need to know
    the cache key in advance so clients can subscribe to updates via Pusher.

    Args:
        queryset: Django QuerySet to generate cache key for
        operation_context: Optional context string (e.g., "min:value", "max:value", "read:fields=...")
                          Used to differentiate aggregate operations on same queryset

    Returns:
        Cache key string or None if cache key cannot be generated
    """
    # Check for transaction ID
    txn_id = current_canonical_id.get()

    # No transaction context = no cache key
    if txn_id is None:
        logger.debug("No canonical_id - cannot generate cache key")
        return None

    # Get SQL
    sql_data = _get_sql_from_queryset(queryset)
    if sql_data is None:
        return None

    sql, params = sql_data

    # Generate cache key
    cache_key = _get_cache_key(sql, params, txn_id, operation_context)

    context_info = f" | Context: {operation_context}" if operation_context else ""
    logger.info(f"Generated cache key for txn {txn_id[:8]}...{context_info} | SQL: {sql[:100]}...")

    return cache_key


def cache_query_result(queryset, result: Dict[str, Any], operation_context: Optional[str] = None) -> None:
    """
    Cache a query result.

    Args:
        queryset: Django QuerySet that was executed
        result: The final serialized result to cache
        operation_context: Optional context string (e.g., "min:value", "max:value")
                          Used to differentiate aggregate operations on same queryset
    """
    # Check for transaction ID
    txn_id = current_canonical_id.get()

    # No transaction context = no caching
    if txn_id is None:
        return

    # Get SQL
    sql_data = _get_sql_from_queryset(queryset)
    if sql_data is None:
        return

    sql, params = sql_data

    # Generate cache key
    cache_key = _get_cache_key(sql, params, txn_id, operation_context)

    # Cache for 1 hour
    try:
        cache.set(cache_key, result, timeout=3600)
        context_info = f" | Context: {operation_context}" if operation_context else ""
        logger.info(f"Cached query result for txn {txn_id[:8]}...{context_info} | SQL: {sql[:100]}...")
    except Exception as e:
        logger.warning(f"Could not cache result: {e}")
