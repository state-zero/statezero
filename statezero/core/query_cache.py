"""
Query-level caching for reads and aggregates.

Caches the FINAL serialized response, keyed by:
- SQL query string (which includes permission filters)
- Query parameters
- Transaction ID (canonical_id)

This provides:
1. Automatic permission safety - permissions are in the SQL
2. Zero invalidation logic - new transaction ID = new cache namespace
3. Caches the complete response - skip execution AND serialization on cache hit
4. Works for both reads and aggregates
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


def get_cached_query_result(queryset, operation_context: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Try to get cached result for a queryset.

    Args:
        queryset: Django QuerySet to check cache for
        operation_context: Optional context string (e.g., "min:value", "max:value")
                          Used to differentiate aggregate operations on same queryset

    Returns:
        Cached result dict or None if not cached
    """
    # Check for transaction ID
    txn_id = current_canonical_id.get()

    # No transaction context = no caching
    if txn_id is None:
        logger.debug("No canonical_id - skipping cache")
        return None

    # Get SQL
    sql_data = _get_sql_from_queryset(queryset)
    if sql_data is None:
        return None

    sql, params = sql_data

    # Generate cache key
    cache_key = _get_cache_key(sql, params, txn_id, operation_context)

    # Try cache
    cached_result = cache.get(cache_key)

    # Record telemetry
    telemetry_ctx = get_telemetry_context()

    if cached_result is not None:
        context_info = f" | Context: {operation_context}" if operation_context else ""
        logger.info(f"Query cache HIT for txn {txn_id[:8]}...{context_info} | SQL: {sql[:100]}...")

        # Record cache hit in telemetry
        if telemetry_ctx:
            telemetry_ctx.record_cache_hit(cache_key, operation_context, sql)

        return cached_result

    context_info = f" | Context: {operation_context}" if operation_context else ""
    logger.debug(f"Query cache MISS for txn {txn_id[:8]}...{context_info} | SQL: {sql[:100]}...")

    # Record cache miss in telemetry
    if telemetry_ctx:
        telemetry_ctx.record_cache_miss(cache_key, operation_context, sql)

    return None


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
