"""
Utilities for namespace-based event filtering.

Namespaces allow selective notification of clients based on simple query filters.
Supports equality checks and __in lookups, including nested fields.
"""
from typing import Any, Dict, List, Optional, Set
import hashlib
import json


def get_direct_value(instance: Any, field_name: str) -> Any:
    """
    Get value from a direct field on the instance (no nested lookups).

    This avoids N+1 queries by only accessing fields directly on the instance,
    not traversing relationships.

    Examples:
        get_direct_value(message, 'room_id') → message.room_id (OK)
        get_direct_value(message, 'status') → message.status (OK)

    Args:
        instance: The model instance
        field_name: Direct field name (no __ allowed)

    Returns:
        The field value, or None if field doesn't exist
    """
    return getattr(instance, field_name, None)


def instance_matches_namespace_filter(instance: Any, namespace: Dict[str, Any]) -> bool:
    """
    Check if an instance matches a namespace filter.

    IMPORTANT: Only direct fields are supported (no nested lookups with __).
    This prevents N+1 queries during event emission.

    Supported:
    - Simple equality: {'room_id': 5}
    - Direct FK fields: {'user_id': 123}
    - __in lookups: {'status__in': ['active', 'pending']}

    NOT supported (silently ignored):
    - Nested lookups: {'room__organization_id': 10}

    Args:
        instance: The model instance to check
        namespace: Dict of field filters (direct fields only)

    Returns:
        True if instance matches all namespace conditions

    Examples:
        >>> message = Message(room_id=5, status='active')
        >>> instance_matches_namespace_filter(message, {'room_id': 5})
        True
        >>> instance_matches_namespace_filter(message, {'room_id': 7})
        False
        >>> instance_matches_namespace_filter(message, {'status__in': ['active', 'pending']})
        True
    """
    for key, expected_value in namespace.items():
        # Handle __in lookups
        if key.endswith('__in'):
            field_name = key[:-4]  # Remove '__in'

            # Check for nested lookups (not allowed) - silently skip
            if '__' in field_name:
                continue

            actual_value = get_direct_value(instance, field_name)

            if actual_value not in expected_value:
                return False
        else:
            # Simple equality check

            # Check for nested lookups (not allowed) - silently skip
            if '__' in key:
                continue

            actual_value = get_direct_value(instance, key)

            if actual_value != expected_value:
                return False

    return True


def extract_namespace_from_filter(query_filter: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract namespace-compatible filters from a query filter.

    Only includes simple equality and __in lookups.
    Excludes complex filters like __gte, __lt, __contains, etc.

    Args:
        query_filter: Full query filter dict

    Returns:
        Namespace dict with only supported filters

    Examples:
        >>> extract_namespace_from_filter({
        ...     'room_id': 5,
        ...     'created_at__gte': '2024-01-01',
        ...     'type__in': ['user', 'system']
        ... })
        {'room_id': 5, 'type__in': ['user', 'system']}
    """
    namespace = {}

    # List of unsupported lookup suffixes
    unsupported = [
        '__gte', '__gt', '__lte', '__lt',
        '__contains', '__icontains',
        '__startswith', '__endswith',
        '__istartswith', '__iendswith',
        '__range', '__isnull',
        '__regex', '__iregex'
    ]

    for key, value in query_filter.items():
        # Skip unsupported lookups
        if any(key.endswith(suffix) for suffix in unsupported):
            continue

        # Include simple equality and __in
        namespace[key] = value

    return namespace


def extract_namespace_from_ast(ast: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract namespace from an AST structure.

    Args:
        ast: The AST dict (full request payload)

    Returns:
        Namespace dict extracted from filter conditions

    Examples:
        >>> ast = {
        ...     "ast": {
        ...         "query": {
        ...             "type": "read",
        ...             "filter": {
        ...                 "type": "filter",
        ...                 "conditions": {"room_id": 5, "created_at__gte": "2024-01-01"}
        ...             }
        ...         }
        ...     }
        ... }
        >>> extract_namespace_from_ast(ast)
        {'room_id': 5}
    """
    # Navigate to filter conditions
    ast_node = ast.get('ast', {})
    query = ast_node.get('query', {})
    filter_node = query.get('filter', {})

    if filter_node and filter_node.get('type') == 'filter':
        conditions = filter_node.get('conditions', {})
        return extract_namespace_from_filter(conditions)

    return {}
