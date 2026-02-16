import warnings
from django.conf import settings
from typing import Any, Dict, Set, Type

def _check_pre_hook_result(
    original_data: Dict, result_data: Any, model: Type, serializer_fields: Set[str]
):
    """Check pre-hook result and warn about common issues in DEBUG mode only."""
    if not getattr(settings, "DEBUG", False):
        return result_data or original_data

    model_name = model.__name__

    # Warning 1: Hook returned None
    if result_data is None:
        warnings.warn(
            f"Pre-hook for {model_name} returned None (should return dict). HINT: If you want to skip changes, return the original data.",
            stacklevel=5,
        )
        return original_data

    if not isinstance(result_data, dict):
        warnings.warn(
            f"Pre-hook for {model_name} returned {type(result_data).__name__} (should return dict). HINT: If you want to skip changes, return the original data.",
            stacklevel=5,
        )
        return original_data

    # Warning 2: Added fields not in serializer
    added_keys = set(result_data.keys()) - set(original_data.keys())
    missing_fields = added_keys - serializer_fields
    if missing_fields:
        warnings.warn(
            f"Pre-hook for {model_name} added unavailable fields {missing_fields}. HINT: Add the field to permission.editable_fields() or use post-hook.",
            stacklevel=5,
        )

    # Warning 3: Removed fields that were in original data
    removed_keys = set(original_data.keys()) - set(result_data.keys())
    if removed_keys:
        warnings.warn(
            f"Pre-hook for {model_name} removed fields {removed_keys} that were in original data. This might be intentional, or it could be caused by a hook not returning the full input data.",
            stacklevel=5,
        )

    return result_data

def _check_post_hook_result(original_data: Dict, result_data: Any, model: Type):
    """Check post-hook result and warn about common issues in DEBUG mode only."""
    if not getattr(settings, "DEBUG", False):
        return result_data or original_data

    model_name = model.__name__

    # Warning 1: Hook returned None
    if result_data is None:
        warnings.warn(
            f"Post-hook for {model_name} returned None (should return dict). HINT: Return the validated_data dict.",
            stacklevel=5,
        )
        return original_data

    if not isinstance(result_data, dict):
        warnings.warn(
            f"Post-hook for {model_name} returned {type(result_data).__name__} (should return dict). HINT: Return the validated_data dict.",
            stacklevel=5,
        )
        return original_data

    # Warning 2: Removed validated fields (more serious than pre-hook)
    removed_keys = set(original_data.keys()) - set(result_data.keys())
    if removed_keys:
        warnings.warn(
            f"Post-hook for {model_name} removed validated fields {removed_keys}. These fields won't be saved.",
            stacklevel=5,
        )

    # Warning 3: Added fields that weren't validated
    added_keys = set(result_data.keys()) - set(original_data.keys())
    if added_keys:
        warnings.warn(
            f"Post-hook for {model_name} added unvalidated fields {added_keys}. These bypassed serializer validation.",
            stacklevel=5,
        )

    return result_data