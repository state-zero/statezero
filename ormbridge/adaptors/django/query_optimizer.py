import logging
from django.db.models import Prefetch, QuerySet
from django.db.models.fields.related import (
    ForeignObjectRel, ManyToManyField, ManyToManyRel, ForeignKey, OneToOneField
)
from django.core.exceptions import FieldDoesNotExist, FieldError

logger = logging.getLogger(__name__)

# Cache for model metadata to avoid repeated lookups
_meta_cache = {}

def _get_model_meta(model):
    """Gets cached model _meta."""
    if model not in _meta_cache:
        _meta_cache[model] = model._meta
    return _meta_cache[model]

def _clear_meta_cache():
    """Clears the meta cache (useful for testing environments)."""
    _meta_cache.clear()

# ================================================================
# Path Generation & VALIDATION (MODIFIED FOR STRICTNESS)
# ================================================================
def generate_query_paths(model, fields):
    """
    Generate relationship paths and map fields to those paths.
    Crucially, validates that *every* requested path segment and the final
    field exist, raising ValueError if not.
    """
    field_map = {'': set()}  # Root model fields
    all_relation_paths = set()
    root_meta = _get_model_meta(model) # Cache root meta

    for field_path in fields:
        parts = field_path.split('__')
        field_name = parts[-1]
        relationship_parts = parts[:-1]

        # --- Strict Validation ---
        current_model = model
        current_meta = root_meta

        # 1. Validate relationship traversal parts
        for i, part in enumerate(relationship_parts):
            try:
                field_obj = current_meta.get_field(part)
                current_path_str = '__'.join(relationship_parts[:i+1])
                all_relation_paths.add(current_path_str) # Add valid relation prefix

                # Determine the next model in the chain
                next_model = None
                if hasattr(field_obj, 'remote_field') and field_obj.remote_field and field_obj.remote_field.model:
                    next_model = field_obj.remote_field.model
                elif hasattr(field_obj, 'related_model') and field_obj.related_model:
                    next_model = field_obj.related_model
                # Check if it's a non-relational field trying to be traversed
                elif not field_obj.is_relation:
                     raise ValueError(
                         f"Path '{field_path}' attempts to traverse non-relational field "
                         f"'{part}' on model {current_model.__name__}."
                     )
                # Check if traversal is possible
                elif not next_model:
                    raise ValueError(
                        f"Cannot determine related model for part '{part}' in path "
                        f"'{field_path}' on model {current_model.__name__}."
                    )

                current_model = next_model
                current_meta = _get_model_meta(current_model) # Get meta for next model

            except FieldDoesNotExist:
                # Raise error if any part of the path is invalid
                raise ValueError(
                    f"Invalid path segment: Field '{part}' not found on model "
                    f"{current_model.__name__} while processing path '{field_path}'."
                )
            except Exception as e: # Catch other potential errors during traversal
                 raise ValueError(
                    f"Error processing segment '{part}' on model {current_model.__name__} "
                    f"for path '{field_path}': {e}"
                 )

        # 2. Validate the final field name on the target model
        try:
            # This get_field call now acts as the final validation
            current_meta.get_field(field_name)
        except FieldDoesNotExist:
             raise ValueError(
                 f"Invalid final field: Field '{field_name}' not found on target model "
                 f"{current_model.__name__} for path '{field_path}'."
             )
        except Exception as e:
             raise ValueError(
                 f"Error validating final field '{field_name}' on model {current_model.__name__} "
                 f"for path '{field_path}': {e}"
             )

        # --- Populate field_map (only if validation passed) ---
        relation_path_key = '__'.join(relationship_parts)
        if relation_path_key not in field_map:
            field_map[relation_path_key] = set()
        field_map[relation_path_key].add(field_name)

    return all_relation_paths, field_map

# ================================================================
# Refine Paths (No Changes Needed)
# ================================================================
def refine_relationship_paths(model, all_relation_paths):
    """
    Refine which paths should use select_related vs prefetch_related.
    (No changes needed here as input paths are now guaranteed to be valid)
    """
    select_related_paths = set()
    prefetch_related_paths = set()

    for path in sorted(list(all_relation_paths), key=len):
        parts = path.split('__')
        current_model = model
        requires_prefetch = False
        valid_path = True # Assume valid as checked upstream
        is_subpath_of_prefetch = False

        for prefetch_path in prefetch_related_paths:
            if path.startswith(prefetch_path + '__'):
                is_subpath_of_prefetch = True
                break
        if is_subpath_of_prefetch:
             prefetch_related_paths.add(path)
             continue

        for part in parts:
            # We assume get_field works here due to upstream validation
            try:
                current_meta = _get_model_meta(current_model)
                field = current_meta.get_field(part)

                if isinstance(field, (ManyToManyField, ManyToManyRel, ForeignObjectRel)):
                    requires_prefetch = True
                    # Upstream validation ensures related_model exists if needed
                    current_model = field.related_model
                elif isinstance(field, (ForeignKey, OneToOneField)):
                     # Upstream validation ensures remote_field.model exists
                     current_model = field.remote_field.model
                else:
                    # This case *shouldn't* happen if upstream validation is correct
                    logger.error(f"Unexpected non-relational field '{part}' encountered "
                                  f"in supposedly validated relation path '{path}'.")
                    valid_path = False; break
            except Exception as e:
                 # Log unexpected errors during refinement, though validation passed
                 logger.error(f"Unexpected error refining validated path '{path}' at part '{part}': {e}")
                 valid_path = False; break

        if valid_path: # Should always be true now
            if requires_prefetch:
                prefetch_related_paths.add(path)
                # Remove select_related paths that are prefixes of this new prefetch
                final_select_related = set(select_related_paths) # Temp copy for iteration
                for sr_path in final_select_related:
                    if path.startswith(sr_path + '__'):
                         if sr_path in select_related_paths:
                            select_related_paths.remove(sr_path)
            else:
                # Only add if not already covered by a prefetch path
                 is_prefix_of_prefetch = False
                 for pf_path in prefetch_related_paths:
                      if pf_path.startswith(path + '__'):
                          is_prefix_of_prefetch = True; break
                 if not is_prefix_of_prefetch:
                     select_related_paths.add(path)

    # Final check for select_related paths being prefixes of prefetch paths
    final_select_related = set(select_related_paths)
    for sr_path in select_related_paths:
        for pf_path in prefetch_related_paths:
            if pf_path.startswith(sr_path + '__'):
                if sr_path in final_select_related:
                    logger.debug(f"Removing '{sr_path}' from select_related as it's covered by prefetch_path '{pf_path}'")
                    final_select_related.remove(sr_path)

    return final_select_related, prefetch_related_paths

# ================================================================
# Redundancy Removal (No Changes Needed)
# ================================================================
def remove_redundant_paths(paths):
    """
    Remove redundant paths for select/prefetch.
    (No changes needed here)
    """
    if not paths:
        return set()

    sorted_paths = sorted(list(paths), key=len, reverse=True)
    result = set(sorted_paths)

    logger.debug(f"remove_redundant_paths input: {paths}")
    logger.debug(f"Sorted paths: {sorted_paths}")

    for i, long_path in enumerate(sorted_paths):
        if long_path not in result:
            continue

        for j in range(i + 1, len(sorted_paths)):
            short_path = sorted_paths[j]
            if short_path not in result:
                continue
            if long_path.startswith(short_path + '__'):
                logger.debug(f"Removing '{short_path}' because '{long_path}' exists and covers it.")
                result.remove(short_path)

    logger.debug(f"remove_redundant_paths output: {result}")
    return result


# ================================================================
# Prefetch Split Helper (No Changes Needed)
# ================================================================
def _find_prefetch_split(start_model, path):
    """
    Finds the first relationship in the path that requires prefetch.
    (No changes needed here, relies on validated paths)
    """
    current_model = start_model
    parts = path.split('__')
    root_prefetch_list = []
    subsequent_list = []
    related_model_after_root = None
    prefetch_found = False

    for i, part in enumerate(parts):
        try:
            current_meta = _get_model_meta(current_model)
            # Assumes get_field works due to upstream validation
            field = current_meta.get_field(part)
            is_prefetch_relation = isinstance(field, (ManyToManyField, ManyToManyRel, ForeignObjectRel))

            next_model = None
            if hasattr(field, 'remote_field') and field.remote_field and field.remote_field.model:
                next_model = field.remote_field.model
            elif hasattr(field, 'related_model') and field.related_model:
                next_model = field.related_model
            # No need for extensive error checks here as path validity is assumed

            if not prefetch_found:
                root_prefetch_list.append(part)
                current_model = next_model
                if is_prefetch_relation:
                    prefetch_found = True
                    related_model_after_root = current_model
            else:
                subsequent_list.append(part)
                current_model = next_model # Continue traversal

        except Exception as e:
            # Should ideally not happen with validated paths, but log defensively
            logger.error(f"Unexpected error splitting validated path '{path}' at part '{part}': {e}")
            return None, None, None

    if prefetch_found:
        root_prefetch_path = '__'.join(root_prefetch_list)
        subsequent_path = '__'.join(subsequent_list)
        return root_prefetch_path, subsequent_path, related_model_after_root
    else:
        # This case means the path didn't actually contain a prefetch-triggering relation,
        # which might indicate an issue in refine_relationship_paths logic if it occurs.
        logger.warning(f"Path '{path}' categorized for prefetch did not contain a prefetch relation during split.")
        return None, None, None


# ================================================================
# MAIN OPTIMIZATION FUNCTION (No Changes Needed for Core Logic)
# ================================================================
def optimize_query(queryset, fields, use_only=True, defer_fields=None):
    """
    Apply select_related, prefetch_related, and only/defer optimizations.
    Relies on generate_query_paths to strictly validate input fields.
    Prefetch building remains simplified (no inner .only()).

    Args:
        queryset: Django QuerySet
        fields (list): List of field paths like ['author__books__publisher', 'author__name'].
                       MUST be valid paths, otherwise generate_query_paths will raise ValueError.
        use_only (bool): If True, use .only() to fetch only needed fields on the
                         ROOT model (based on field_map[''] + required FKs + PK).
                         Defaults to True.
        defer_fields (list, optional): List of fields to exclude from the root
                                       queryset using .defer().

    Returns:
        QuerySet: Optimized queryset

    Raises:
        ValueError: If any path in `fields` is invalid (segment not found,
                    final field not found, or attempts to traverse non-relation).
        TypeError: If queryset is not a QuerySet instance.
        FieldError: Potential Django error during .only()/.defer() application if
                    conflicts arise (less likely with validation).
    """
    # --- Initial checks and setup ---
    if not isinstance(queryset, QuerySet):
        raise TypeError("queryset must be a Django QuerySet instance.")

    model = queryset.model
    _clear_meta_cache() # Clear cache for fresh run

    # If no fields specified, apply defer if needed, otherwise return original
    # No validation needed if fields list is empty.
    if not fields:
        logger.info("No fields specified, returning original queryset.")
        if defer_fields:
             # Basic validation for defer_fields even when no specific fields requested
             valid_defer_fields = []
             root_meta = _get_model_meta(model)
             for field_name in defer_fields:
                 try:
                     root_meta.get_field(field_name)
                     valid_defer_fields.append(field_name)
                 except FieldDoesNotExist:
                      logger.warning(f"Field '{field_name}' specified in defer_fields not found on {model.__name__}. Skipping.")
             if valid_defer_fields:
                  logger.info(f"Applying .defer({valid_defer_fields}) as specified (no fields list)")
                  return queryset.defer(*valid_defer_fields)
             else:
                  logger.warning("No valid fields found in defer_fields. Not applying .defer().")
        return queryset

    # 1. Generate potential paths and the field map (CRITICAL VALIDATION STEP)
    # This will raise ValueError if any input field path is invalid.
    try:
        all_relation_paths, field_map = generate_query_paths(model, fields)
    except ValueError as e:
        logger.error(f"Input field validation failed: {e}")
        _clear_meta_cache()
        raise # Re-raise the validation error

    # --- Continue with optimization if validation passed ---
    try:
        # 2. Determine which paths use select_related vs prefetch_related
        select_related_paths, prefetch_related_paths = refine_relationship_paths(
            model, all_relation_paths
        )

        # 3. Remove redundant paths for top-level application
        final_select_related = remove_redundant_paths(select_related_paths)

        logger.debug(f"--- Optimization Plan for {model.__name__} ---")
        logger.debug(f"  Input Fields (Validated): {fields}")
        # Log raw paths determined *after* validation
        # logger.debug(f"  Raw Select Related Paths: {select_related_paths}") # Maybe less useful now
        # logger.debug(f"  Raw Prefetch Related Paths: {prefetch_related_paths}")
        logger.debug(f"  Final Select Related: {final_select_related}")
        logger.debug(f"  Final Prefetch Paths (Roots): {prefetch_related_paths}") # Log the paths going into prefetch loop
        logger.debug(f"  Field Map (Validated): {field_map}")
        logger.debug(f"  Use Only (Root): {use_only}")
        logger.debug(f"  Defer Fields (Root): {defer_fields}")

        # Keep track of the original queryset for potential error reporting
        original_queryset = queryset # Although queryset gets modified below
        prefetch_data = {} # Dictionary to store Prefetch build info

        # Apply top-level select_related first
        if final_select_related:
            logger.info(f"Applying select_related({final_select_related})")
            queryset = queryset.select_related(*final_select_related)
        else:
            logger.info("No select_related paths to apply.")

        # ================================================================
        # Build Prefetch objects (Simplified - No Inner .only())
        # ================================================================
        for path in prefetch_related_paths:
            split_result = _find_prefetch_split(model, path)
            if not split_result or not split_result[0]:
                logger.warning(f"Skipping prefetch build for path '{path}' - split failed unexpectedly.")
                continue # Skip if path doesn't represent a valid prefetch structure

            root_pf_path, subsequent_path, related_model = split_result

            if root_pf_path not in prefetch_data:
                 prefetch_data[root_pf_path] = {
                     'related_model': related_model,
                     'nested_selects': set(),
                 }

            current_pf_info = prefetch_data[root_pf_path]

            # --- Determine nested select_related path ---
            is_nested_select_path = True
            current_nested_model = related_model
            if subsequent_path:
                sub_parts = subsequent_path.split('__')
                temp_nested_select_parts = []
                for part in sub_parts:
                     try:
                         if not current_nested_model:
                            is_nested_select_path = False; break
                         meta = _get_model_meta(current_nested_model)
                         # Assume get_field works here
                         field = meta.get_field(part)
                         # Check it *is* a select-compatible relation
                         if not isinstance(field, (ForeignKey, OneToOneField)):
                             is_nested_select_path = False; break

                         next_model = field.remote_field.model if hasattr(field, 'remote_field') and field.remote_field else None
                         if not next_model: # Should have been caught upstream if needed for path
                            is_nested_select_path = False; break

                         current_nested_model = next_model
                         temp_nested_select_parts.append(part)
                     except Exception: # Catch unexpected issues even here
                         is_nested_select_path = False; break
                if is_nested_select_path and temp_nested_select_parts:
                    current_pf_info['nested_selects'].add(subsequent_path)

        # --- Now, build the actual Prefetch objects from the aggregated data ---
        prefetch_objects = []
        for root_pf_path, pf_info in prefetch_data.items():
            related_model = pf_info['related_model']
            if not related_model:
                logger.warning(f"Cannot build Prefetch for '{root_pf_path}': related model unknown.")
                continue

            inner_queryset = related_model._default_manager.all() # Start with default manager

            # Apply nested select_related if any were found
            final_nested_selects = remove_redundant_paths(pf_info['nested_selects'])
            if final_nested_selects:
                logger.debug(f"  Applying nested select_related({final_nested_selects}) within Prefetch('{root_pf_path}')")
                inner_queryset = inner_queryset.select_related(*final_nested_selects)

            # Create the final Prefetch object (NO .only() here)
            prefetch_obj = Prefetch(root_pf_path, queryset=inner_queryset)
            prefetch_objects.append(prefetch_obj)

            # Construct representation for logging (Simplified)
            qs_repr_parts = [f"{related_model.__name__}.objects"]
            if final_nested_selects:
                qs_repr_parts.append(f".select_related({final_nested_selects})")
            qs_repr = "".join(qs_repr_parts)
            logger.info(f"Prepared Prefetch('{root_pf_path}', queryset={qs_repr})")

        # Apply prefetch_related with the constructed objects
        if prefetch_objects:
            logger.info(f"Applying prefetch_related with {len(prefetch_objects)} optimized Prefetch objects.")
            queryset = queryset.prefetch_related(*prefetch_objects)
        else:
             logger.info("No prefetch_related paths requiring optimized Prefetch objects.")

        # --- Apply .only() or .defer() for the ROOT queryset ---
        apply_defer = bool(defer_fields)
        apply_only = False
        root_fields_to_fetch = set() # Define here for error logging scope

        if use_only:
            root_meta = _get_model_meta(model)
            pk_name = root_meta.pk.name

            # Add direct non-relational fields requested for the root model
            # These are guaranteed to exist by generate_query_paths
            if '' in field_map:
                for field_name in field_map.get('', set()):
                    try: # Still good practice to handle unexpected field type issues
                        field_obj = root_meta.get_field(field_name)
                        if not field_obj.is_relation:
                           root_fields_to_fetch.add(field_name)
                        # Also add FK fields if explicitly requested directly
                        elif isinstance(field_obj, (ForeignKey, OneToOneField)):
                             root_fields_to_fetch.add(field_obj.attname)
                    except FieldDoesNotExist: # Should not happen after validation
                        logger.error(f"Validated field '{field_name}' unexpectedly not found on root model {model.__name__} during .only() phase.")
                    except Exception as e:
                         logger.error(f"Error processing root field '{field_name}' for .only(): {e}")

            # Always include the primary key if using .only()
            if pk_name: root_fields_to_fetch.add(pk_name)

            # Add the foreign key fields required by top-level select_related paths
            # These paths/fields are also guaranteed valid by generate_query_paths
            if final_select_related:
                for path in final_select_related:
                    first_part = path.split('__')[0]
                    try:
                        field_obj = root_meta.get_field(first_part)
                        # Only add FK attribute names (e.g., 'author_id')
                        if isinstance(field_obj, (ForeignKey, OneToOneField)):
                            root_fields_to_fetch.add(field_obj.attname)
                    except FieldDoesNotExist: # Should not happen
                        logger.error(f"Validated field '{first_part}' from select_related path '{path}' unexpectedly not found on {model.__name__} during .only() phase.")
                    except Exception as e:
                        logger.error(f"Error processing select_related path '{path}' for .only(): {e}")

            # Determine if .only() should actually be applied
            if root_fields_to_fetch:
                apply_only = True
                apply_defer = False # .only() takes precedence if use_only=True
            else:
                 # This case is unlikely if PK exists, but defensively:
                 apply_only = False
                 logger.warning(f"use_only=True but no root fields identified for .only() on {model.__name__}. Not applying .only().")

        # Apply .only() or .defer()
        if apply_only:
            logger.info(f"Applying .only({root_fields_to_fetch}) to root queryset.")
            queryset = queryset.only(*root_fields_to_fetch)
        elif apply_defer:
             # Validate defer fields again just in case they weren't checked earlier
             # (e.g., if fields was empty but defer_fields was provided)
             valid_defer_fields = []
             root_meta = _get_model_meta(model)
             for field_name in defer_fields:
                 try:
                     root_meta.get_field(field_name)
                     valid_defer_fields.append(field_name)
                 except FieldDoesNotExist:
                      logger.warning(f"Field '{field_name}' specified in defer_fields not found on {model.__name__}. Skipping.")
             if valid_defer_fields:
                  logger.info(f"Applying .defer({valid_defer_fields}) to root queryset.")
                  queryset = queryset.defer(*valid_defer_fields)
             else:
                  logger.warning("No valid fields found in defer_fields. Not applying .defer().")
        else:
             logger.info("Not applying .only() or .defer() to root queryset.")

    # --- Error Handling ---
    except FieldError as e:
        # This might still occur if .only/.defer conflicts with internal Django needs
        # for filtering/ordering not covered by our explicit fields.
        logger.error(f"FieldError during optimization application: {e}. Possible conflict between only/defer and other queryset operations.")
        logger.error(f"  Model: {model.__name__}")
        logger.error(f"  Validated Fields requested: {fields}")
        logger.error(f"  Select Related paths: {final_select_related}")
        logger.error(f"  Prefetch Data Prepared: {prefetch_data}") # Log structure used
        logger.error(f"  Calculated root .only() fields: {root_fields_to_fetch if 'root_fields_to_fetch' in locals() else 'Not Calculated'}")
        logger.error(f"  Specified .defer() fields: {defer_fields}")
        _clear_meta_cache()
        raise e
    except Exception as e:
        logger.exception(f"An unexpected error occurred during query optimization: {e}")
        _clear_meta_cache()
        raise e

    _clear_meta_cache()
    logger.debug(f"--- Optimization finished for {model.__name__} ---")
    return queryset


# ================================================================
# generate_paths Helper (No Changes Needed)
# ================================================================
def generate_paths(model, depth, fields, get_model_name):
    """
    Generates relationship paths up to a given depth for specified fields.
    (No changes needed here, not directly related to the core optimization logic)
    """
    # ... (implementation remains the same) ...
    paths = set()

    def _traverse(current_model, current_path, current_depth):
        if current_depth > depth:
            return

        model_name = get_model_name(current_model)

        # Add fields for the current model
        if model_name in fields:
            for field in fields[model_name]:
                full_path = current_path + ("__" if current_path else "") + field
                paths.add(full_path) # Assumes field is valid on current_model here

        # Traverse related fields *if they are also requested*
        meta = _get_model_meta(current_model)  # Use the cached meta
        for field in meta.get_fields():
            # Check if it's a relation AND if the relation itself is listed in fields dict for current model
            if field.concrete and field.is_relation and model_name in fields and field.name in fields[model_name]:
                field_name = field.name
                related_model = None
                if hasattr(field, 'remote_field') and field.remote_field and field.remote_field.model:
                    related_model = field.remote_field.model
                elif hasattr(field, 'related_model') and field.related_model:
                    related_model = field.related_model

                if related_model:
                    new_path = current_path + ("__" if current_path else "") + field_name
                    _traverse(related_model, new_path, current_depth + 1)

    _traverse(model, "", 0)
    return paths