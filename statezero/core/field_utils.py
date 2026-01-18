"""
Field utilities for extracting and merging fields from filter/exclude AST nodes.
"""

from typing import Any, Dict, List, Set


# Shared lookup operators used for stripping from field paths
SUPPORTED_OPERATORS = frozenset({
    "contains",
    "icontains",
    "startswith",
    "istartswith",
    "endswith",
    "iendswith",
    "lt",
    "gt",
    "lte",
    "gte",
    "in",
    "eq",
    "exact",
    "isnull",
})


def strip_lookup_operator(field_path: str) -> str:
    """
    Strip lookup operators from a field path.

    Examples:
        "status__in" -> "status"
        "name__icontains" -> "name"
        "user__email__icontains" -> "user__email"
        "created_at__gte" -> "created_at"
    """
    parts = field_path.split("__")
    # Find where the lookup operators start and keep everything before
    base_parts = []
    for part in parts:
        if part in SUPPORTED_OPERATORS:
            break
        base_parts.append(part)
    return "__".join(base_parts) if base_parts else field_path


def extract_fields_from_filter(filter_node: Dict[str, Any]) -> Set[str]:
    """
    Recursively extract field names from filter/exclude AST nodes.
    Strips lookup operators (__icontains, __gt, etc).

    Handles both simple conditions and nested AND/OR structures.

    Args:
        filter_node: A filter or exclude AST node

    Returns:
        Set of field paths (with lookup operators stripped)
    """
    if not filter_node or not isinstance(filter_node, dict):
        return set()

    fields: Set[str] = set()
    node_type = filter_node.get("type")

    # Handle filter/exclude nodes with conditions
    if node_type in ("filter", "exclude"):
        conditions = filter_node.get("conditions", {})
        for field_path in conditions.keys():
            stripped = strip_lookup_operator(field_path)
            if stripped:
                fields.add(stripped)

    # Handle AND/OR nodes
    if node_type in ("and", "or"):
        children = filter_node.get("children", [])
        for child in children:
            fields |= extract_fields_from_filter(child)

    # Handle NOT nodes
    if node_type == "not":
        child = filter_node.get("child")
        if child:
            fields |= extract_fields_from_filter(child)

    # Recursively check children and child
    if "children" in filter_node:
        for child in filter_node["children"]:
            fields |= extract_fields_from_filter(child)

    if "child" in filter_node:
        fields |= extract_fields_from_filter(filter_node["child"])

    return fields


def merge_fields_with_filter_fields(
    requested_fields: List[str],
    filter_fields: Set[str],
) -> List[str]:
    """
    Merge requested fields with filter/exclude fields.
    Filter fields are implicitly required to make filters work correctly.

    Args:
        requested_fields: User-requested fields from serializerOptions
        filter_fields: Fields extracted from filter/exclude AST nodes

    Returns:
        Merged list of fields with filter fields included
    """
    if not filter_fields:
        return requested_fields

    # Start with requested fields as a set for deduplication
    merged = set(requested_fields) if requested_fields else set()

    # Add filter fields
    merged |= filter_fields

    # Return as list, maintaining some order (requested fields first)
    result = list(requested_fields) if requested_fields else []
    for field in sorted(filter_fields):
        if field not in result:
            result.append(field)

    return result
