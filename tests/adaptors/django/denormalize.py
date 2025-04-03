from typing import Any, Dict, List, Optional, Union


def denormalize(normalized_response: Dict[str, Any]) -> Any:
    """
    Transforms a normalized response back into a nested structure.
    
    Args:
        normalized_response: A dictionary containing 'data' and 'included' keys
        
    Returns:
        The denormalized data with nested objects instead of references,
        preserving the original structure (dict for single object, list for many)
    """
    if not isinstance(normalized_response, dict):
        return normalized_response
        
    if 'data' not in normalized_response or 'included' not in normalized_response:
        return normalized_response
    
    data = normalized_response['data']
    included = normalized_response['included']
    
    # The data field could be a single object or a list of objects
    # We need to maintain the same structure as the original output
    return _denormalize_entity(data, included)


def _denormalize_entity(entity: Any, included: Dict[str, Dict[str, Any]]) -> Any:
    """
    Recursively denormalizes an entity and its nested references.
    
    Args:
        entity: The entity or collection of entities to denormalize
        included: The dictionary of included entities
        
    Returns:
        The denormalized entity with all references replaced by their full objects
    """
    # Handle list of entities
    if isinstance(entity, list):
        return [_denormalize_entity(item, included) for item in entity]
    
    # If not a dict or doesn't have type/id, return as is
    if not isinstance(entity, dict):
        return entity
    
    # Check if this is a reference object (has 'type' and 'id' keys only)
    if set(entity.keys()) == {'type', 'id'} or (len(entity) > 2 and 'type' in entity and 'id' in entity):
        # This is a reference, get the full entity from included
        entity_type = entity['type']
        entity_id = entity['id']
        
        if entity_type not in included or str(entity_id) not in included[entity_type]:
            # Reference not found, return as is
            return entity
            
        # Get the full entity
        full_entity = included[entity_type][str(entity_id)]
        # Denormalize the full entity recursively
        return _denormalize_entity(full_entity, included)
    
    # This is a regular entity, denormalize all its fields
    result = {}
    for field_name, field_value in entity.items():
        result[field_name] = _denormalize_entity(field_value, included)
    
    return result


def verify_identical(original, denormalized):
    """
    Verifies that a denormalized object is identical to the original nested object.
    
    Args:
        original: The original nested object
        denormalized: The denormalized object
        
    Returns:
        bool: True if the objects are identical, False otherwise
    """
    if isinstance(original, list) and isinstance(denormalized, list):
        if len(original) != len(denormalized):
            return False
        return all(verify_identical(o, d) for o, d in zip(original, denormalized))
    
    if isinstance(original, dict) and isinstance(denormalized, dict):
        if set(original.keys()) != set(denormalized.keys()):
            return False
        return all(verify_identical(original[k], denormalized[k]) for k in original.keys())
    
    return original == denormalized