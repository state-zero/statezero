import logging
from django.db import models
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

# Helper function to get model and pk at the end of a path
# (Keep this helper as it might still be useful, though not directly for inner .only() now)
def _get_model_and_pk_at_path(start_model, path):
    """
    Traverses a relationship path and returns the final model class and its pk name.
    """
    current_model = start_model
    if not path:
        meta = _get_model_meta(current_model)
        return current_model, meta.pk.name

    parts = path.split('__')
    for i, part in enumerate(parts):
        try:
            current_meta = _get_model_meta(current_model)
            field_obj = current_meta.get_field(part)

            related_model = None
            if hasattr(field_obj, 'remote_field') and field_obj.remote_field and field_obj.remote_field.model:
                related_model = field_obj.remote_field.model
            elif hasattr(field_obj, 'related_model') and field_obj.related_model:
                related_model = field_obj.related_model

            if related_model:
                current_model = related_model
            else:
                if i == len(parts) - 1 and not field_obj.is_relation:
                    logger.debug(f"Path part '{part}' in '{path}' is not a relationship on {current_model.__name__}. Path ends here.")
                    # Return the current model as the final one, even though the last part isn't a relation itself
                    final_meta = _get_model_meta(current_model)
                    return current_model, final_meta.pk.name
                elif not field_obj.is_relation:
                    logger.warning(f"Path part '{part}' in '{path}' on {current_model.__name__} is not a traversable relation.")
                    return None, None
                else:
                    logger.warning(f"Cannot determine related model for part '{part}' in path '{path}' on model {current_model.__name__}.")
                    return None, None

        except FieldDoesNotExist:
            logger.warning(f"Field '{part}' not found on {current_model.__name__} for path '{path}'.")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error getting model at path '{path}' part '{part}': {e}")
            return None, None

    final_meta = _get_model_meta(current_model)
    return current_model, final_meta.pk.name


def generate_query_paths(model, fields):
    """
    Generate potential relationship paths and map fields to those paths.
    (No changes needed here)
    """
    field_map = {'': set()}  # Root model fields
    all_relation_paths = set()

    for field_path in fields:
        parts = field_path.split('__')

        if len(parts) == 1:
            field_map[''].add(field_path)
            continue

        field_name = parts[-1]
        relationship_parts = parts[:-1]
        current_model = model
        valid_path_found = True
        current_path_str = ''
        last_valid_model_in_path = model

        for i, part in enumerate(relationship_parts):
            try:
                current_meta = _get_model_meta(current_model)
                field_obj = current_meta.get_field(part)
                current_path_str = '__'.join(relationship_parts[:i+1])
                all_relation_paths.add(current_path_str)

                next_model = None
                if hasattr(field_obj, 'remote_field') and field_obj.remote_field and field_obj.remote_field.model:
                    next_model = field_obj.remote_field.model
                elif hasattr(field_obj, 'related_model') and field_obj.related_model:
                    next_model = field_obj.related_model

                if next_model:
                    current_model = next_model
                    last_valid_model_in_path = current_model
                else:
                    logger.warning(f"Cannot determine related model for part '{part}' in path '{field_path}' on model {current_model.__name__}.")
                    try:
                         _get_model_meta(last_valid_model_in_path).get_field(field_name)
                         current_model = last_valid_model_in_path
                    except FieldDoesNotExist:
                         logger.warning(f"Field '{field_name}' also not found on last valid model {last_valid_model_in_path.__name__}. Path '{field_path}' seems invalid.")
                         valid_path_found = False
                    break

            except FieldDoesNotExist:
                logger.warning(f"Field '{part}' not found on {current_model.__name__} for path '{field_path}'. Skipping field.")
                valid_path_found = False
                break

        if valid_path_found:
            relation_path_key = '__'.join(relationship_parts)
            if relation_path_key not in field_map:
                field_map[relation_path_key] = set()
            try:
                _get_model_meta(current_model).get_field(field_name)
                field_map[relation_path_key].add(field_name)
            except FieldDoesNotExist:
                 logger.warning(f"Field '{field_name}' not found on final model {current_model.__name__} for path '{field_path}'. Skipping field addition to map.")

        elif len(relationship_parts) > 1 :
            last_valid_path_key = '__'.join(relationship_parts[:-1])
            if last_valid_path_key in all_relation_paths:
                if last_valid_path_key not in field_map:
                    field_map[last_valid_path_key] = set()
                if len(parts) >= 2:
                    field_map[last_valid_path_key].add(relationship_parts[-1])
            else:
                 if parts: field_map[''].add(parts[0])
        elif len(relationship_parts) == 1:
            if parts: field_map[''].add(parts[0])

    return all_relation_paths, field_map


def refine_relationship_paths(model, all_relation_paths):
    """
    Refine which paths should use select_related vs prefetch_related.
    (No changes needed here)
    """
    select_related_paths = set()
    prefetch_related_paths = set()

    for path in sorted(list(all_relation_paths), key=len):
        parts = path.split('__')
        current_model = model
        requires_prefetch = False
        valid_path = True
        is_subpath_of_prefetch = False

        for prefetch_path in prefetch_related_paths:
            if path.startswith(prefetch_path + '__'):
                is_subpath_of_prefetch = True
                break
        if is_subpath_of_prefetch:
             prefetch_related_paths.add(path)
             continue

        for part in parts:
            try:
                current_meta = _get_model_meta(current_model)
                field = current_meta.get_field(part)

                if isinstance(field, (ManyToManyField, ManyToManyRel, ForeignObjectRel)):
                    requires_prefetch = True
                    if hasattr(field, 'related_model') and field.related_model:
                        current_model = field.related_model
                    else:
                         logger.warning(f"Could not get related model for M2M/Reverse FK '{part}' in path '{path}'.")
                         valid_path = False; break
                elif isinstance(field, (ForeignKey, OneToOneField)):
                     if not field.remote_field or not field.remote_field.model:
                         logger.warning(f"Could not follow FK/O2O '{part}' in path '{path}' - no remote model found.")
                         valid_path = False; break
                     current_model = field.remote_field.model
                else:
                    logger.warning(f"Field '{part}' in path '{path}' is not a traversable relation.")
                    valid_path = False; break

            except FieldDoesNotExist:
                logger.warning(f"Field '{part}' not found on {current_model.__name__} while refining path '{path}'.")
                valid_path = False; break
            except Exception as e:
                 logger.error(f"Unexpected error refining path '{path}' at part '{part}': {e}")
                 valid_path = False; break

        if valid_path:
            if requires_prefetch:
                prefetch_related_paths.add(path)
            else:
                select_related_paths.add(path)
        else:
            pass

    final_select_related = set(select_related_paths)
    for sr_path in select_related_paths:
        for pf_path in prefetch_related_paths:
            if pf_path.startswith(sr_path + '__'):
                if sr_path in final_select_related:
                    logger.debug(f"Removing '{sr_path}' from select_related as it's covered by prefetch_path '{pf_path}'")
                    final_select_related.remove(sr_path)

    return final_select_related, prefetch_related_paths


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
# Helper Function to determine first prefetch step and subsequent path
# (Keep this helper)
# ================================================================
def _find_prefetch_split(start_model, path):
    """
    Finds the first relationship in the path that requires prefetch.
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
            field = current_meta.get_field(part)
            is_prefetch_relation = isinstance(field, (ManyToManyField, ManyToManyRel, ForeignObjectRel))

            next_model = None
            if hasattr(field, 'remote_field') and field.remote_field and field.remote_field.model:
                next_model = field.remote_field.model
            elif hasattr(field, 'related_model') and field.related_model:
                next_model = field.related_model

            if not next_model and i < len(parts) -1 :
                 logger.warning(f"Cannot determine next model for '{part}' in path '{path}'. Split failed.")
                 return None, None, None

            if not prefetch_found:
                root_prefetch_list.append(part)
                current_model = next_model
                if is_prefetch_relation:
                    prefetch_found = True
                    related_model_after_root = current_model
            else:
                subsequent_list.append(part)
                # Only continue traversal if next_model is valid
                if next_model:
                    current_model = next_model
                elif i < len(parts) -1: # If not the last part, traversal failed
                    logger.warning(f"Cannot traverse subsequent path for '{part}' in '{path}'.")
                    # Don't invalidate the split, just subsequent path might be incomplete
                    pass


        except FieldDoesNotExist:
            logger.warning(f"Field '{part}' not found on model while splitting path '{path}'. Split failed.")
            return None, None, None
        except Exception as e:
            logger.error(f"Error splitting path '{path}' at part '{part}': {e}")
            return None, None, None

    if prefetch_found:
        root_prefetch_path = '__'.join(root_prefetch_list)
        subsequent_path = '__'.join(subsequent_list)
        return root_prefetch_path, subsequent_path, related_model_after_root
    else:
        return None, None, None


# ================================================================
# MAIN OPTIMIZATION FUNCTION (Simplified Prefetch Building)
# ================================================================
def optimize_query(queryset, fields, use_only=True, defer_fields=None):
    """
    Apply select_related, prefetch_related, and only/defer optimizations.
    Prefetch building simplified for robustness - focuses on nested select_related
    within Prefetch, but removes automatic inner .only().

    Args:
        queryset: Django QuerySet
        fields (list): List of field paths like ['author__books__publisher', 'author__name']
        use_only (bool): If True, use .only() to fetch only needed fields on the
                         ROOT model. Defaults to True. Inner .only() for Prefetch
                         is disabled in this version.
        defer_fields (list, optional): List of fields to exclude from the root
                                       queryset using .defer().

    Returns:
        QuerySet: Optimized queryset
    """
    # --- Initial checks and setup ---
    if not isinstance(queryset, QuerySet):
        raise TypeError("queryset must be a Django QuerySet instance.")
    if not fields:
        logger.info("No fields specified, returning original queryset.")
        if defer_fields:
             logger.info(f"Applying .defer({defer_fields}) as specified (no fields list)")
             return queryset.defer(*defer_fields)
        return queryset

    model = queryset.model
    _clear_meta_cache()

    # 1. Generate potential paths and the field map
    all_relation_paths, field_map = generate_query_paths(model, fields)

    # 2. Determine which paths use select_related vs prefetch_related
    select_related_paths, prefetch_related_paths = refine_relationship_paths(
        model, all_relation_paths
    )

    # 3. Remove redundant paths for top-level application
    final_select_related = remove_redundant_paths(select_related_paths)

    logger.debug(f"--- Optimization Plan for {model.__name__} ---")
    logger.debug(f"  Input Fields: {fields}")
    logger.debug(f"  Raw Select Related Paths: {select_related_paths}")
    logger.debug(f"  Raw Prefetch Related Paths: {prefetch_related_paths}") # Log full set
    logger.debug(f"  Final Select Related: {final_select_related}")
    logger.debug(f"  Field Map: {field_map}")
    logger.debug(f"  Use Only (Root): {use_only}")
    logger.debug(f"  Defer Fields (Root): {defer_fields}")

    original_queryset = queryset
    prefetch_data = {} # Dictionary to store Prefetch build info

    try:
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
                continue # Skip if path doesn't represent a valid prefetch structure

            root_pf_path, subsequent_path, related_model = split_result

            if root_pf_path not in prefetch_data:
                 prefetch_data[root_pf_path] = {
                     'related_model': related_model,
                     'nested_selects': set(),
                     # We no longer need 'required_fields' inside prefetch_data
                 }

            current_pf_info = prefetch_data[root_pf_path]

            # --- Determine nested select_related path ---
            # (Same logic as before to check if subsequent_path is select-like)
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
                         field = meta.get_field(part)
                         if isinstance(field, (ManyToManyField, ManyToManyRel, ForeignObjectRel)):
                             is_nested_select_path = False; break
                         if not isinstance(field, (ForeignKey, OneToOneField)):
                              is_nested_select_path = False; break

                         next_model = None
                         if hasattr(field, 'remote_field') and field.remote_field and field.remote_field.model:
                             next_model = field.remote_field.model

                         if not next_model:
                             is_nested_select_path = False; break
                         current_nested_model = next_model
                         temp_nested_select_parts.append(part)
                     except FieldDoesNotExist:
                         is_nested_select_path = False; break
                if is_nested_select_path and temp_nested_select_parts:
                    current_pf_info['nested_selects'].add(subsequent_path)

            # --- Accumulate required fields - REMOVED ---
            # We don't need to track required fields for inner .only() anymore


        # --- Now, build the actual Prefetch objects from the aggregated data ---
        prefetch_objects = []
        for root_pf_path, pf_info in prefetch_data.items():
            related_model = pf_info['related_model']
            if not related_model: continue

            inner_queryset = related_model._default_manager.all() # Start with default manager

            # Apply nested select_related if any were found
            final_nested_selects = remove_redundant_paths(pf_info['nested_selects'])
            if final_nested_selects:
                logger.debug(f"  Applying nested select_related({final_nested_selects}) within Prefetch('{root_pf_path}')")
                inner_queryset = inner_queryset.select_related(*final_nested_selects)

            # --- REMOVED: .only() application within Prefetch ---

            # Create the final Prefetch object
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


        # --- Apply .only() or .defer() for the ROOT queryset (Logic Remains the Same) ---
        apply_defer = bool(defer_fields)
        apply_only = False
        root_fields_to_fetch = set() # Define here for error logging scope

        if use_only:
            root_meta = _get_model_meta(model)
            pk_name = root_meta.pk.name

            # Add direct non-relational fields requested for the root model
            if '' in field_map:
                for field_name in field_map.get('', set()):
                    try:
                        field_obj = root_meta.get_field(field_name)
                        if not field_obj.is_relation:
                           root_fields_to_fetch.add(field_name)
                        elif isinstance(field_obj, (ForeignKey, OneToOneField)):
                             root_fields_to_fetch.add(field_obj.attname)
                    except FieldDoesNotExist:
                        logger.warning(f"Field '{field_name}' requested in 'only' for root model {model.__name__} not found.")

            if pk_name: root_fields_to_fetch.add(pk_name)

            # Add the foreign key fields required by top-level select_related paths
            if final_select_related:
                for path in final_select_related:
                    first_part = path.split('__')[0]
                    try:
                        field_obj = root_meta.get_field(first_part)
                        if isinstance(field_obj, (ForeignKey, OneToOneField)):
                            root_fields_to_fetch.add(field_obj.attname)
                    except FieldDoesNotExist:
                        logger.error(f"Field '{first_part}' from select_related path '{path}' not found on {model.__name__}.")
                    except Exception as e:
                        logger.error(f"Error processing select_related path '{path}' for .only(): {e}")

            if root_fields_to_fetch:
                apply_only = True
                apply_defer = False
            elif pk_name: # Fetch only PK if use_only=True but no other fields needed
                 apply_only = True
                 root_fields_to_fetch = {pk_name}
                 apply_defer = False
            else:
                 apply_only = False

        # Apply .only() or .defer()
        if apply_only:
            logger.info(f"Applying .only({root_fields_to_fetch}) to root queryset.")
            queryset = queryset.only(*root_fields_to_fetch)
        elif apply_defer:
             logger.info(f"Applying .defer({defer_fields}) to root queryset.")
             valid_defer_fields = []
             root_meta = _get_model_meta(model)
             for field_name in defer_fields:
                 try:
                     root_meta.get_field(field_name)
                     valid_defer_fields.append(field_name)
                 except FieldDoesNotExist:
                      logger.warning(f"Field '{field_name}' specified in defer_fields not found on {model.__name__}. Skipping.")
             if valid_defer_fields:
                  queryset = queryset.defer(*valid_defer_fields)
             else:
                  logger.warning("No valid fields found in defer_fields. Not applying .defer().")
        else:
             logger.info("Not applying .only() or .defer() to root queryset.")

    # --- Error Handling ---
    except FieldError as e:
        logger.error(f"FieldError during optimization: {e}. Possible conflict between only/defer and related lookups.")
        logger.error(f"  Model: {model.__name__}")
        logger.error(f"  Fields requested: {fields}")
        logger.error(f"  Select Related paths: {final_select_related}")
        logger.error(f"  Prefetch Data Prepared: {prefetch_data}") # Log structure used
        logger.error(f"  Calculated root .only() fields: {root_fields_to_fetch}")
        logger.error(f"  Specified .defer() fields: {defer_fields}")
        raise e
    except Exception as e:
        logger.exception(f"An unexpected error occurred during query optimization: {e}")
        raise e

    _clear_meta_cache()
    logger.debug(f"--- Optimization finished for {model.__name__} ---")
    return queryset