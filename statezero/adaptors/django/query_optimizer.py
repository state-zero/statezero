import logging
from django.db.models import Prefetch, QuerySet
from django.db.models.fields.related import (
    ForeignObjectRel, ManyToManyField, ManyToManyRel, ForeignKey, OneToOneField, ManyToOneRel
)

from typing import Optional, Dict, Set, Callable, Type, Any, List, Union
from django.db.models import Model
from django.core.exceptions import FieldDoesNotExist, FieldError
from django.db.models.constants import LOOKUP_SEP
from contextvars import ContextVar

from statezero.core.interfaces import AbstractQueryOptimizer

logger = logging.getLogger(__name__)

# Cache for model metadata
_meta_cache_var = ContextVar('_meta_cache', default={})

"""
This module implements a Django QuerySet optimizer that intelligently applies
`select_related`, `prefetch_related`, and optionally `.only()` to reduce the
number of database queries and the amount of data transferred.

**Vibe Coded with Gemini**

This code was co-authored with Google Gemini because the specific behaviours of the
orm are difficult to reason about. This should eventually be verified and enhanced -
the overall behaviours are verified in the tests to make sure that query counts reduce
and runtimes improve.

**Detailed Explanation:**

The core logic resides within the `optimize_query` function. This function takes a
Django QuerySet and a specification of the desired fields to retrieve as input and
returns an optimized QuerySet.  It intelligently determines the optimal combination
of `select_related`, `prefetch_related`, and `.only()` calls to minimize database
interactions.

1.  **Field Path Generation and Validation (`generate_query_paths`):**  The
    process begins by validating the provided field paths.  The
    `generate_query_paths` function parses each field path (e.g.,
    `'author__profile__bio'`) and verifies that each segment of the path exists
    as a valid field on the corresponding model.  It also identifies whether
    each relationship along the path is a `ForeignKey`, `OneToOneField`,
    `ManyToManyField`, or a reverse relation.  This validation ensures that the
    specified fields are actually accessible and helps prevent runtime errors. It
    returns two structures: `all_relation_paths`, a set of all relationship paths,
    and `field_map`, a dictionary mapping relation paths to the fields that should
    be fetched at the end of that relationship.

2.  **Relationship Path Refinement (`refine_relationship_paths`):**  After
    validation, the `refine_relationship_paths` function analyzes the relationship
    paths to determine whether to use `select_related` or `prefetch_related`.
    `select_related` is used for `ForeignKey` and `OneToOneField` relationships,
    while `prefetch_related` is used for `ManyToManyField` and reverse
    relationships.  The function intelligently handles nested relationships,
    ensuring that the most efficient approach is used for each path.

3.  **Redundancy Removal (`remove_redundant_paths`):** This function removes
    redundant paths. For example, if you request both 'a' and 'a__b', requesting
    'a' becomes redundant because 'a__b' will automatically fetch 'a' as well.

4.  **Prefetch Splitting (`_find_prefetch_split`):** This helper function finds
    the first prefetch-requiring relation in a path and splits the path into a root
    prefetch path and a subsequent path. This is necessary for constructing
    `Prefetch` objects with inner querysets for nested optimizations.

5.  **`Prefetch` Object Construction:** For each `prefetch_related` path, the
    code constructs a `Prefetch` object.  It finds any nested `select_related`
    paths *within* the prefetched relationship and applies them to the inner
    queryset of the `Prefetch` object. It also restricts the fields fetched by the
    inner queryset using `.only()` based on the specified fields_map.

6.  **`.only()` Application:**  If enabled via the `use_only` parameter, the
    code applies `.only()` to the root QuerySet.  It includes only the fields
    explicitly requested via the `fields_map`, as well as any foreign key fields
    required by the `select_related` paths. This ensures that only the necessary
    data is retrieved from the database.

7.  **Error Handling:**  The code includes comprehensive error handling to catch
    `FieldDoesNotExist`, `FieldError`, and other exceptions that may occur during
    the optimization process.  Error messages are logged to provide detailed
    information about the cause of the error.

8.  **Caching:**  Model metadata is cached to improve performance by avoiding
    repeated calls to `model._meta`.

9.  **`generate_paths` Function:** This utility function is used to
    automatically generate field paths based on a depth parameter and a
    `fields_map`.  It is used when the user does not provide an explicit list of
    fields to optimize.

10. **`DjangoQueryOptimizer` Class:** This class implements the
    `AbstractQueryOptimizer` interface, providing a reusable and configurable way
    to optimize Django QuerySets.  It allows users to specify the depth of
    relationship traversal, the fields to retrieve for each model, and a function
    to get a consistent string name for a model class.

**How it Works:**

The optimizer works by analyzing the structure of the requested data and
intelligently constructing a series of `select_related`, `prefetch_related`, and
`.only()` calls.  `select_related` eagerly loads related objects in the same
database query, which is efficient for `ForeignKey` and `OneToOneField`
relationships. `prefetch_related` performs a separate query for each related
object, which is necessary for `ManyToManyField` and reverse relationships.
`.only()` restricts the fields that are retrieved from the database, reducing the
amount of data transferred.

By combining these techniques, the optimizer can significantly reduce the number of
database queries and the amount of data transferred, resulting in improved
application performance.
"""

def _get_model_meta(model):
    """Gets cached model _meta using context variable."""
    meta_cache = _meta_cache_var.get()
    if model not in meta_cache:
        meta_cache[model] = model._meta
        # Update the context variable with the modified cache
        _meta_cache_var.set(meta_cache)
    return meta_cache[model]

def _clear_meta_cache():
    """Clears the meta cache in the current context."""
    _meta_cache_var.set({})

# ================================================================
# Path Generation & VALIDATION (Strict)
# ================================================================
def generate_query_paths(model, fields):
    """Generate relationship paths and map fields, validating strictly."""
    field_map = {'': set()}
    all_relation_paths = set()
    root_meta = _get_model_meta(model)

    for field_path in fields:
        parts = field_path.split(LOOKUP_SEP)
        field_name = parts[-1]
        relationship_parts = parts[:-1]
        current_model = model
        current_meta = root_meta

        for i, part in enumerate(relationship_parts):
            try:
                field_obj = current_meta.get_field(part)
                current_path_str = LOOKUP_SEP.join(relationship_parts[:i+1])
                all_relation_paths.add(current_path_str)
                next_model = getattr(field_obj, 'related_model', None) or \
                             (getattr(field_obj, 'remote_field', None) and getattr(field_obj.remote_field, 'model', None))
                if not field_obj.is_relation:
                     raise ValueError(f"Path '{field_path}' traverses non-relational field '{part}' on {current_model.__name__}.")
                if not next_model:
                    raise ValueError(f"Cannot determine related model for '{part}' in path '{field_path}' on {current_model.__name__}.")
                current_model = next_model
                current_meta = _get_model_meta(current_model)
            except FieldDoesNotExist:
                raise ValueError(f"Invalid path segment: '{part}' not found on {current_model.__name__} processing '{field_path}'.")
            except Exception as e:
                 raise ValueError(f"Error processing segment '{part}' on {current_model.__name__} for path '{field_path}': {e}")

        try:
            current_meta.get_field(field_name)
        except FieldDoesNotExist:
             raise ValueError(f"Invalid final field: '{field_name}' not found on {current_model.__name__} for path '{field_path}'.")
        except Exception as e:
             raise ValueError(f"Error validating final field '{field_name}' on {current_model.__name__} for path '{field_path}': {e}")

        relation_path_key = LOOKUP_SEP.join(relationship_parts)
        field_map.setdefault(relation_path_key, set()).add(field_name)

    return all_relation_paths, field_map

# ================================================================
# Refine Paths
# ================================================================
def refine_relationship_paths(model, all_relation_paths):
    """Refine paths into select_related vs prefetch_related."""
    select_related_paths = set()
    prefetch_related_paths = set()

    for path in sorted(list(all_relation_paths), key=len):
        parts = path.split(LOOKUP_SEP)
        current_model = model
        requires_prefetch = False
        valid_path = True
        is_subpath_of_prefetch = any(path.startswith(p + LOOKUP_SEP) for p in prefetch_related_paths)

        if is_subpath_of_prefetch:
             prefetch_related_paths.add(path)
             continue

        for part in parts:
            try:
                current_meta = _get_model_meta(current_model)
                field = current_meta.get_field(part)
                if isinstance(field, (ManyToManyField, ManyToManyRel, ForeignObjectRel, ManyToOneRel)):
                    requires_prefetch = True
                    # Ensure related_model is valid before assignment
                    related_model = getattr(field, 'related_model', None)
                    if not related_model:
                        raise ValueError(f"Cannot determine related model for prefetch field '{part}' on {current_model.__name__}")
                    current_model = related_model
                elif isinstance(field, (ForeignKey, OneToOneField)):
                     # Ensure remote_field and model are valid
                     remote_field = getattr(field, 'remote_field', None)
                     if not remote_field or not getattr(remote_field, 'model', None):
                          raise ValueError(f"Cannot determine related model for FK/O2O field '{part}' on {current_model.__name__}")
                     current_model = remote_field.model
                else: # Should not happen with validation
                    logger.error(f"Unexpected non-relational field '{part}' in validated path '{path}'.")
                    valid_path = False; break
            except Exception as e:
                 logger.error(f"Unexpected error refining path '{path}' at part '{part}': {e}")
                 valid_path = False; break

        if valid_path:
            if requires_prefetch:
                prefetch_related_paths.add(path)
                paths_to_remove = {sr for sr in select_related_paths if path.startswith(sr + LOOKUP_SEP)}
                select_related_paths.difference_update(paths_to_remove)
            else:
                 is_prefix_of_prefetch = any(pf.startswith(path + LOOKUP_SEP) for pf in prefetch_related_paths)
                 if not is_prefix_of_prefetch:
                     select_related_paths.add(path)

    # Final cleanup
    final_select_related = set(select_related_paths)
    for sr_path in select_related_paths:
        if any(pf_path.startswith(sr_path + LOOKUP_SEP) for pf_path in prefetch_related_paths):
            final_select_related.discard(sr_path)

    return final_select_related, prefetch_related_paths


# ================================================================
# Redundancy Removal
# ================================================================
def remove_redundant_paths(paths):
    """Remove redundant paths (e.g., 'a' if 'a__b' exists)."""
    if not paths: return set()
    # Sort by length descending to check longer paths against shorter ones
    sorted_paths = sorted(list(paths), key=len, reverse=True)
    result = set(sorted_paths) # Start with all paths
    to_remove = set() # Keep track of paths to remove

    for i, long_path in enumerate(sorted_paths):
        # If long_path itself was already removed, skip checks for it
        if long_path in to_remove:
            continue
        # Check against all shorter paths that come after it in the sorted list
        for j in range(i + 1, len(sorted_paths)):
            short_path = sorted_paths[j]
            # If short_path was already marked for removal, skip
            if short_path in to_remove:
                continue
            # Check if the long path starts with the short path + separator
            if long_path.startswith(short_path + LOOKUP_SEP):
                # Mark the shorter path for removal
                logger.debug(f"Marking '{short_path}' for removal because '{long_path}' exists.")
                to_remove.add(short_path)

    # Remove the marked paths from the result set
    result.difference_update(to_remove)
    logger.debug(f"remove_redundant_paths input: {paths}")
    logger.debug(f"remove_redundant_paths output: {result}")
    return result

# ================================================================
# Prefetch Split Helper
# ================================================================
def _find_prefetch_split(start_model, path):
    """Finds the first prefetch-requiring relation and splits the path."""
    current_model = start_model
    parts = path.split(LOOKUP_SEP)
    root_prefetch_list = []
    subsequent_list = []
    related_model_after_root = None
    prefetch_found = False

    for i, part in enumerate(parts):
        try:
            current_meta = _get_model_meta(current_model)
            field = current_meta.get_field(part)
            is_prefetch_relation = isinstance(field, (ManyToManyField, ManyToManyRel, ForeignObjectRel, ManyToOneRel))
            next_model = getattr(field, 'related_model', None) or \
                         (getattr(field, 'remote_field', None) and getattr(field.remote_field, 'model', None))

            if not prefetch_found:
                root_prefetch_list.append(part)
                # Need the next model to continue, even if prefetch not found yet
                if not next_model and i < len(parts) - 1: # Check if not the last part
                     raise ValueError(f"Cannot determine next model for non-prefetch part '{part}' in '{path}'")
                current_model = next_model
                if is_prefetch_relation:
                    prefetch_found = True
                    related_model_after_root = current_model # The model *being* prefetched
            else:
                subsequent_list.append(part)
                 # Need to continue stepping through models for subsequent path
                if not next_model and i < len(parts) - 1:
                     raise ValueError(f"Cannot determine next model for subsequent part '{part}' in '{path}'")
                current_model = next_model

        except Exception as e:
            logger.error(f"Error splitting path '{path}' at part '{part}': {e}")
            return None, None, None # Return three Nones

    if prefetch_found:
        root_prefetch_path = LOOKUP_SEP.join(root_prefetch_list)
        subsequent_path = LOOKUP_SEP.join(subsequent_list)
        return root_prefetch_path, subsequent_path, related_model_after_root
    else:
        # This path didn't actually contain a prefetch relation
        logger.warning(f"Path '{path}' ended up in prefetch logic but contained no prefetch relation.")
        return None, None, None

# ================================================================
# MAIN OPTIMIZATION FUNCTION
# ================================================================
def optimize_query(queryset, fields=None, fields_map=None, depth=0, use_only=True, get_model_name=None):
    """
    Apply select_related, prefetch_related, and optionally .only() optimizations.
    Uses either:
    1.  A list of field paths (fields). In this case it still relies on the field map to get which models will be selected.
    2.  A fields_map and depth to automatically generate paths.

    Args:
        queryset: Django QuerySet
        fields (list, optional): List of field paths.
        fields_map (dict, optional): Dictionary specifying fields to retrieve for each model,
                                     with model names obtained using get_model_name.
        depth (int, optional):  Depth of relationships to traverse when using fields_map.
        use_only (bool): If True, use .only() on the root model.
        get_model_name (callable, optional): Function to get model name from a model class.
                                               Required if using fields_map or if 'fields' is used with 'fields_map'.

    Returns:
        QuerySet: Optimized queryset
    """
    if not isinstance(queryset, QuerySet):
        raise TypeError("queryset must be a Django QuerySet instance.")

    model = queryset.model
    _clear_meta_cache()

    # Validate get_model_name if fields_map is used or fields is used along with fields_map
    if (fields_map or fields) and not callable(get_model_name):
        raise ValueError("If 'fields_map' or 'fields' with 'fields_map' is provided, 'get_model_name' must be a callable function.")

    # 1. Generate paths either from explicit field list or fields_map/depth
    if fields:
        try:
            all_relation_paths, field_map = generate_query_paths(model, fields)
        except ValueError as e:
            logger.error(f"Input field validation failed: {e}")
            _clear_meta_cache()
            raise

    elif fields_map:
        # Generate paths from fields_map and depth
        if get_model_name is None:
            raise ValueError("get_model_name must be provided when using fields_map")
        generated_paths = generate_paths(model, depth, fields_map, get_model_name)
        fields = list(generated_paths)  # Convert set to list
        #Generate fields from generated paths to be used in only clause for the root model

        all_relation_paths = set()
        field_map = {'': set()}

        for field_path in fields:
            parts = field_path.split(LOOKUP_SEP)
            field_name = parts[-1]
            relationship_parts = parts[:-1]
            relation_path_key = LOOKUP_SEP.join(relationship_parts)
            field_map.setdefault(relation_path_key, set()).add(field_name)
            if relationship_parts:
                all_relation_paths.add(relation_path_key)


    else:
        logger.info("No fields or fields_map specified, returning original queryset.")
        return queryset

    # --- Continue with optimization ---
    try:
        # 2. Determine which paths use select_related vs prefetch_related
        select_related_paths, prefetch_related_paths = refine_relationship_paths(
            model, all_relation_paths
        )

        # 3. Remove redundant paths for top-level application
        final_select_related = remove_redundant_paths(select_related_paths)

        logger.debug(f"--- Optimization Plan for {model.__name__} ---")
        logger.debug(f"  Input Fields (Validated): {fields}")
        logger.debug(f"  Final Select Related: {final_select_related}")
        logger.debug(f"  All Prefetch Paths (to process): {prefetch_related_paths}")
        logger.debug(f"  Field Map (Validated): {field_map}")
        logger.debug(f"  Use Only (Root): {use_only}") # Log use_only parameter
        logger.debug(f"  Fields Map (Passed In): {fields_map}")

        prefetch_data = {} # Dictionary to store Prefetch build info

        # Apply top-level select_related first
        if final_select_related:
            logger.info(f"Applying select_related({final_select_related})")
            queryset = queryset.select_related(*final_select_related)
        else:
            logger.info("No select_related paths to apply.")

        # ================================================================
        # Build Prefetch objects
        # ================================================================
        processed_prefetch_roots = set() # Track roots to build only one Prefetch per root path
        prefetch_objects = []

        # Process prefetch paths, potentially building nested select_related inside
        for path in prefetch_related_paths:
            split_result = _find_prefetch_split(model, path)
            if not split_result or not split_result[0]:
                logger.debug(f"Skipping prefetch build for path '{path}' - split failed or no prefetch found.")
                continue # Skip if path doesn't represent a valid prefetch structure

            root_pf_path, subsequent_path, related_model = split_result

            if not related_model:
                 logger.warning(f"Cannot determine related model for prefetch '{root_pf_path}'. Skipping.")
                 continue

            # Aggregate nested select info for this root path
            if root_pf_path not in prefetch_data:
                 prefetch_data[root_pf_path] = {
                     'related_model': related_model,
                     'nested_selects': set(),
                 }
            # Add subsequent path if it represents a valid nested select_related chain
            if subsequent_path:
                # Basic check: Does subsequent path contain prefetch-like relations? If not, assume select_related.
                # (More robust check could re-run refine_paths logic on subsequent path relative to related_model)
                is_nested_select = True
                current_nested_model = related_model
                try:
                    for part in subsequent_path.split(LOOKUP_SEP):
                         meta = _get_model_meta(current_nested_model)
                         field = meta.get_field(part)
                         if not isinstance(field, (ForeignKey, OneToOneField)):
                             is_nested_select = False; break
                         current_nested_model = field.remote_field.model
                except Exception:
                     is_nested_select = False

                if is_nested_select:
                    prefetch_data[root_pf_path]['nested_selects'].add(subsequent_path)
                else:
                     logger.debug(f"Subsequent path '{subsequent_path}' for root '{root_pf_path}' is not purely select_related.")

        # --- Now, build the actual Prefetch objects ---
        for root_pf_path, pf_info in prefetch_data.items():
            # Avoid creating duplicate Prefetch objects for the same root
            if root_pf_path in processed_prefetch_roots:
                continue

            related_model = pf_info['related_model']
            inner_queryset = related_model._default_manager.all()

            # Apply nested select_related if any were found for this root
            final_nested_selects = remove_redundant_paths(pf_info['nested_selects'])
            if final_nested_selects:
                logger.debug(f"  Applying nested select_related({final_nested_selects}) within Prefetch('{root_pf_path}')")
                inner_queryset = inner_queryset.select_related(*final_nested_selects)

            # --- Apply .only() to the INNER queryset (the one *being* prefetched) ---
            related_model_name = get_model_name(related_model)

            related_fields_to_fetch = set()

            if fields_map and related_model_name in fields_map:
                # Process each field, checking for custom serializers
                from statezero.adaptors.django.serializers import get_custom_serializer
                related_meta = _get_model_meta(related_model)
                for field_name in fields_map[related_model_name]:
                    try:
                        field_obj = related_meta.get_field(field_name)
                        if not field_obj.is_relation:
                            # Check if this field has a custom serializer with explicit DB field requirements
                            custom_serializer = get_custom_serializer(field_obj.__class__)
                            if custom_serializer and hasattr(custom_serializer, 'get_prefetch_db_fields'):
                                # Use the explicit list from the custom serializer
                                db_fields = custom_serializer.get_prefetch_db_fields(field_name)
                                for db_field in db_fields:
                                    related_fields_to_fetch.add(db_field)
                                logger.debug(f"Using custom DB fields {db_fields} for field '{field_name}' in {related_model_name}")
                            else:
                                # No custom serializer, just add the field itself
                                related_fields_to_fetch.add(field_name)
                        else:
                            # Relation field, add as-is
                            related_fields_to_fetch.add(field_name)
                    except FieldDoesNotExist:
                        # Field doesn't exist, add it anyway (might be computed)
                        related_fields_to_fetch.add(field_name)
                    except Exception as e:
                        logger.error(f"Error checking custom serializer for field '{field_name}' in {related_model_name}: {e}")
                        # On error, add the field anyway to be safe
                        related_fields_to_fetch.add(field_name)
            else:
                # If no field restrictions are provided, get all fields
                all_fields = [f.name for f in related_model._meta.get_fields() if f.concrete]
                related_fields_to_fetch.update(all_fields)
                logger.debug(f"No fields_map provided for {related_model_name}.  Fetching all fields.")

            # Always add PK
            related_fields_to_fetch.add(related_model._meta.pk.name)

            if related_fields_to_fetch:
                logger.debug(f"  Applying .only({related_fields_to_fetch}) to inner queryset for Prefetch('{root_pf_path}')")
                try:
                    inner_queryset = inner_queryset.only(*related_fields_to_fetch)
                except FieldError as e:
                    logger.error(f"FieldError applying .only({related_fields_to_fetch}) to {related_model_name} for prefetch: {e}")
                    raise

            # Create the final Prefetch object
            prefetch_obj = Prefetch(root_pf_path, queryset=inner_queryset)
            prefetch_objects.append(prefetch_obj)
            processed_prefetch_roots.add(root_pf_path)

            # Construct representation for logging
            qs_repr_parts = [f"{related_model.__name__}.objects"]
            if final_nested_selects:
                qs_repr_parts.append(f".select_related({final_nested_selects})")
            if related_fields_to_fetch:
                qs_repr_parts.append(f".only({related_fields_to_fetch})")
            qs_repr = "".join(qs_repr_parts)
            logger.info(f"Prepared Prefetch('{root_pf_path}', queryset={qs_repr})")

        # Apply prefetch_related with the constructed objects
        if prefetch_objects:
            logger.info(f"Applying prefetch_related with {len(prefetch_objects)} optimized Prefetch objects.")
            queryset = queryset.prefetch_related(*prefetch_objects) # Apply unique prefetches
        else:
             logger.info("No prefetch_related paths requiring optimized Prefetch objects.")

        # --- Apply .only() for the ROOT queryset IF use_only is True ---
        # This section is restored to its state before use_only was removed
        apply_only = False
        root_fields_to_fetch = set()

        if use_only: # Check the parameter
            root_meta = _get_model_meta(model)
            pk_name = root_meta.pk.name

            # Add direct non-relational fields requested for the root model
            if '' in field_map:
                for field_name in field_map.get('', set()):
                    try:
                        field_obj = root_meta.get_field(field_name)
                        if not field_obj.is_relation:
                           # Check if this field has a custom serializer with explicit DB field requirements
                           from statezero.adaptors.django.serializers import get_custom_serializer
                           custom_serializer = get_custom_serializer(field_obj.__class__)
                           if custom_serializer and hasattr(custom_serializer, 'get_prefetch_db_fields'):
                               # Use the explicit list from the custom serializer
                               db_fields = custom_serializer.get_prefetch_db_fields(field_name)
                               for db_field in db_fields:
                                   root_fields_to_fetch.add(db_field)
                               logger.debug(f"Using custom DB fields {db_fields} for field '{field_name}'")
                           else:
                               # No custom serializer, just add the field itself
                               root_fields_to_fetch.add(field_name)
                        elif isinstance(field_obj, (ForeignKey, OneToOneField)):
                             # If FK/O2O itself is requested directly, include its id field
                             root_fields_to_fetch.add(field_obj.attname)
                    except FieldDoesNotExist: # Should not happen after validation
                        logger.error(f"Validated field '{field_name}' unexpectedly not found on root model {model.__name__} during .only() phase.")
                    except Exception as e:
                         logger.error(f"Error processing root field '{field_name}' for .only(): {e}")

            # Always include the primary key if using .only()
            if pk_name: root_fields_to_fetch.add(pk_name)

            # Add the foreign key fields (_id) required by top-level select_related paths
            if final_select_related:
                for path in final_select_related:
                    first_part = path.split(LOOKUP_SEP)[0]
                    try:
                        field_obj = root_meta.get_field(first_part)
                        # Only add FK/O2O attribute names (e.g., 'author_id')
                        if isinstance(field_obj, (ForeignKey, OneToOneField)):
                            root_fields_to_fetch.add(field_obj.attname)
                    except FieldDoesNotExist: # Should not happen
                        logger.error(f"Validated field '{first_part}' from select_related path '{path}' unexpectedly not found on {model.__name__} during .only() phase.")
                    except Exception as e:
                        logger.error(f"Error processing select_related path '{path}' for .only(): {e}")

            # Determine if .only() should actually be applied
            if root_fields_to_fetch:
                apply_only = True # Set flag to true only if use_only=True and fields were found
            else:
                 apply_only = False
                 logger.warning(f"use_only=True but no root fields identified for .only() on {model.__name__}. Not applying .only().")

        # Apply .only() based on the apply_only flag (which depends on use_only)
        if apply_only:
            logger.info(f"Applying .only({root_fields_to_fetch}) to root queryset.")
            try:
                 queryset = queryset.only(*root_fields_to_fetch)
            except FieldError as e:
                 logger.error(f"FieldError applying .only({root_fields_to_fetch}) to {model.__name__}: {e}. Check for conflicts with annotations or ordering.")
                 raise # Re-raise FieldError as it indicates a real problem
        # No 'elif apply_defer' block anymore
        else:
             # This logs if use_only=False OR if use_only=True but no fields were calculated
             logger.info("Not applying .only() to root queryset (use_only=False or no fields identified).")

    # --- Error Handling ---
    except FieldError as e:
        # Catch FieldErrors that might occur during select_related/prefetch_related too
        logger.error(f"FieldError during optimization application: {e}.")
        _clear_meta_cache()
        raise e
    except ValueError as e: # Catch validation errors
        logger.error(f"Field validation or processing error: {e}")
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
# generate_paths Helper (No changes needed from original provided)
# ================================================================
def generate_paths(model, depth, fields, get_model_name):
    """
    Generates relationship paths up to a given depth for specified fields dict.
    """
    paths = set()
    processed_models = set() # Avoid infinite loops

    def _traverse(current_model, current_path, current_depth):
        model_identifier = (current_model, current_path)
        if current_depth > depth or model_identifier in processed_models:
            return
        processed_models.add(model_identifier)

        model_name = get_model_name(current_model)
        current_meta = _get_model_meta(current_model)

        if model_name in fields:
            model_fields_to_include = fields[model_name]
            for field_name in model_fields_to_include:
                try:
                    field_obj = current_meta.get_field(field_name)
                    full_path = current_path + (LOOKUP_SEP if current_path else "") + field_name
                    paths.add(full_path) # Add the path ending here

                    # If it's a relation and we should traverse further
                    if field_obj.is_relation:
                        related_model = getattr(field_obj, 'related_model', None) or \
                                        (getattr(field_obj, 'remote_field', None) and getattr(field_obj.remote_field, 'model', None))
                        if related_model and get_model_name(related_model) in fields:
                             _traverse(related_model, full_path, current_depth + 1)
                except FieldDoesNotExist:
                     logger.warning(f"[generate_paths] Field '{field_name}' specified in 'fields' dict not found on model {model_name} at path '{current_path}'. Skipping.")
                     continue

    _traverse(model, "", 0)
    _clear_meta_cache()
    logger.debug(f"[generate_paths] Generated paths: {paths}")
    # Note: This generate_paths does basic path building based on the dict keys/values.
    # It does *not* guarantee the same level of strict validation as the internal generate_query_paths.
    # The main optimize_query function relies on its *internal* generate_query_paths for validation.
    return paths

def optimize_individual_model(model_instance, fields_map=None, depth=0, use_only=True, get_model_name=None):
    """
    Optimizes fetching a single model instance using select_related, prefetch_related, and .only().
    """
    if not isinstance(model_instance, Model):
        raise TypeError("model_instance must be a Django Model instance.")

    model_class = model_instance.__class__

    #Check for related fields before proceeding to optimization
    any_related_fields = False

    if fields_map:
            for model_name, model_fields in fields_map.items():
                for field in model_fields:
                    if '__' in field:  # If there's a related field its length is >1
                        any_related_fields = True
                        break
                if any_related_fields:
                    break
    #If there are no related fields, return the instance with no extra queries.
    if not any_related_fields:
        logger.info("No related fields requested. Skipping optimization.")
        return model_instance
    try:
        # 1. Turn the instance into a queryset.
        queryset = model_class.objects.filter(pk=model_instance.pk)

        # 2. Optimize the queryset using the shared optimization logic.
        optimized_queryset = optimize_query(
            queryset,
            fields=None, #Let fields_map handle field validation and path creation
            fields_map=fields_map,
            depth=depth,
            use_only=use_only,
            get_model_name=get_model_name
        )

        # 3. Extract the optimized instance.
        optimized_instance = optimized_queryset.first()

        return optimized_instance

    except Exception as e:
        logger.exception(f"An error occurred during individual model optimization: {e}")
        raise

class DjangoQueryOptimizer(AbstractQueryOptimizer):
    """
    Concrete implementation of AbstractQueryOptimizer for Django QuerySets.
    """
    def __init__(
        self,
        depth: Optional[int] = None,
        fields_per_model: Optional[Dict[str, Set[str]]] = None,
        get_model_name_func: Optional[Callable[[Type[Model]], str]] = None,
        use_only: bool = True
    ):
        """
        Initializes the optimizer with configuration parameters.

        Args:
            depth (Optional[int]): Maximum relationship traversal depth
                if generating field paths automatically.
            fields_per_model (Optional[Dict[str, Set[str]]]): Mapping of
                model names (keys) to sets of required field/relationship names
                (values), used if generating field paths automatically.
            get_model_name_func (Optional[Callable]): Function to get a
                consistent string name for a model class.
            use_only (bool): Whether to use .only() on the root model.
        """
        self.depth = depth
        self.fields_per_model = fields_per_model
        self.get_model_name_func = get_model_name_func
        self.use_only = use_only
        
        # Validate configuration
        if (fields_per_model or depth is not None) and not get_model_name_func:
            raise ValueError("If 'fields_per_model' or 'depth' is provided, 'get_model_name_func' must also be provided.")
        
        if depth is not None and depth < 0:
            raise ValueError("Depth cannot be negative.")

    def optimize(
        self,
        queryset: Union[QuerySet, Model],
        fields: Optional[List[str]] = None
    ) -> Union[QuerySet, Model]:
        """
        Optimizes the given Django QuerySet or Model instance.

        Args:
            queryset (Union[QuerySet, Model]): The Django QuerySet or Model instance to optimize.
            fields (Optional[List[str]]): An explicit list of field paths to optimize for.
                If provided, this overrides automatic path generation.
            **kwargs: Optional overrides for depth, fields_map, get_model_name_func, or use_only.

        Returns:
            Union[QuerySet, Model]: The optimized QuerySet or Model instance.
        """
        # Handle optional overrides
        depth = self.depth
        fields_map = self.fields_per_model
        get_model_name_func = self.get_model_name_func
        use_only = self.use_only

        if isinstance(queryset, Model):
            # Optimize a single model instance
            return optimize_individual_model(
                queryset,
                fields_map=fields_map,
                depth=depth,
                use_only=use_only,
                get_model_name=get_model_name_func
            )
        elif isinstance(queryset, QuerySet):
            #Optimize a queryset object.
            optimized_queryset = optimize_query(
                queryset,
                fields=fields,
                fields_map=fields_map,
                depth=depth,
                use_only=use_only,
                get_model_name=get_model_name_func,
            )

            return optimized_queryset
        else:
            raise TypeError("Input must be a QuerySet or a Model instance.")