from typing import Any, Dict, List, Optional, Union

def denormalize(normalized_response: Dict[str, Any]) -> Any:
    """
    Transforms a normalized JSON:API-like response back into a nested structure,
    correctly handling cyclic references.

    Args:
        normalized_response: A dictionary expected to contain 'data' and 'included' keys.
                             'data' can be a single entity reference/object or a list.
                             'included' maps model types to dictionaries of entities by ID.

    Returns:
        The denormalized data with nested objects instead of references,
        preserving the original structure (dict for single object, list for many).
        Returns the input if it doesn't match the expected normalized structure.
    """
    if not isinstance(normalized_response, dict):
        # Input is not a dictionary, cannot be the expected normalized format.
        return normalized_response

    if 'data' not in normalized_response or 'included' not in normalized_response:
        # Missing required keys. Might be already denormalized or just a plain dict.
        # Return as is, assuming it's not the target format for this function.
        return normalized_response

    data = normalized_response['data']
    included = normalized_response['included']

    # Memoization cache for the current denormalization call.
    # Stores objects that have already been processed or are in processing
    # to break cycles. Key: tuple(type, str(id)), Value: denormalized object
    memo: Dict[tuple[str, str], Any] = {}

    # Start the recursive denormalization process
    return _denormalize_entity(data, included, memo)


def _denormalize_entity(entity: Any, included: Dict[str, Dict[str, Any]], memo: Dict[tuple[str, str], Any]) -> Any:
    """
    Recursively denormalizes an entity (or list of entities) and its nested
    references, using memoization to handle cycles.

    Args:
        entity: The entity (dict), reference (dict with type/id), list of entities/references,
                or primitive value to denormalize.
        included: The dictionary of included entities from the normalized response.
        memo: Dictionary tracking already processed entities (type, id) -> object
              within the current denormalization call.

    Returns:
        The denormalized entity/list/value with references replaced by their full objects.
    """
    # 1. Handle lists: Recursively denormalize each item
    if isinstance(entity, list):
        return [_denormalize_entity(item, included, memo) for item in entity]

    # 2. Handle non-dictionary types: Return primitives/other types directly
    if not isinstance(entity, dict):
        return entity

    # 3. Identify potential entities/references (must have 'type' and 'id')
    entity_type = entity.get('type')
    entity_id = entity.get('id') # ID can be int or string, normalize to string for lookup

    if entity_type is not None and entity_id is not None:
        # Standardize the key for lookup and memoization
        entity_key = (entity_type, str(entity_id))

        # --- Cycle / Memoization Check ---
        if entity_key in memo:
            # This object is already being processed or has been completed.
            # Return the memoized reference/object immediately to break the cycle.
            return memo[entity_key]
        # --- End Cycle Check ---

        # Determine if this dictionary represents the full data or just a reference
        is_reference_only = set(entity.keys()) == {'type', 'id'}

        # Find the complete data for this entity
        full_entity_data = None
        if entity_type in included and entity_key[1] in included[entity_type]:
            # Found the full data in the 'included' section
            full_entity_data = included[entity_type][entity_key[1]]
        elif not is_reference_only:
            # This dictionary itself contains more than just type/id,
            # assume it's the full data (e.g., the root object in 'data').
            full_entity_data = entity
        else:
            # It's a reference {'type': T, 'id': I}, but the full data
            # wasn't found in 'included'. This might indicate an incomplete
            # response or an error. Return the reference as is.
            return entity

        # --- Memoization: Store placeholder *before* recursion ---
        # Create the object that will be populated. Store it in the memo immediately.
        # If recursion leads back here, the memo check above will return this object.
        denormalized_object = {}
        memo[entity_key] = denormalized_object
        # --- End Placeholder ---

        # Recursively denormalize all fields using the full entity data
        for field_name, field_value in full_entity_data.items():
             denormalized_object[field_name] = _denormalize_entity(field_value, included, memo)

        # The denormalized_object (which was also stored in memo) is now fully populated
        return denormalized_object

    else:
        # 4. Handle generic dictionaries (without type/id):
        # This dictionary doesn't represent a normalized entity (no type/id).
        # Recursively process its values like a regular nested structure.
        # Example: the 'repr' field {'str': '...', 'img': '...'}
        result = {}
        for field_name, field_value in entity.items():
            result[field_name] = _denormalize_entity(field_value, included, memo)
        return result


# --- Verification Helper (Optional but useful) ---

def verify_identical(original, denormalized):
    """
    Recursively verifies that a denormalized object is identical in structure
    and values to the original nested object.

    Args:
        original: The original nested object (list or dict).
        denormalized: The denormalized object (list or dict).

    Returns:
        bool: True if the objects are identical, False otherwise.
    """
    # Check type mismatch
    if type(original) is not type(denormalized):
        print(f"Type mismatch: {type(original)} vs {type(denormalized)}")
        return False

    # Compare lists
    if isinstance(original, list):
        if len(original) != len(denormalized):
            print(f"List length mismatch: {len(original)} vs {len(denormalized)}")
            return False
        # Recursively compare each item in the list
        return all(verify_identical(o, d) for o, d in zip(original, denormalized))

    # Compare dictionaries
    if isinstance(original, dict):
        if set(original.keys()) != set(denormalized.keys()):
            print(f"Dict key mismatch: {original.keys()} vs {denormalized.keys()}")
            return False
        # Recursively compare each value in the dictionary
        return all(verify_identical(original[k], denormalized[k]) for k in original.keys())

    # Compare primitive values
    if original != denormalized:
        print(f"Value mismatch: {original} vs {denormalized}")
        return False

    # If all checks pass
    return True