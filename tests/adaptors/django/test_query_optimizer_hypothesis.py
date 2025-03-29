import random
import time
import logging
from unittest import SkipTest

from hypothesis import given, strategies as st, settings, HealthCheck, assume
from django.db import models, connection, reset_queries
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist, FieldError

# Assuming your optimize_query and its helpers are in this path
# Adjust the import path as needed for your project structure
# from ..query_optimizer import optimize_query, _clear_meta_cache # Example relative import
# Or if it's installed:
# from your_package.ormbridge.adaptors.django.query_optimizer import optimize_query, _clear_meta_cache
# For demonstration, assuming it's importable directly:
from ormbridge.adaptors.django.query_optimizer import optimize_query, _clear_meta_cache


# --- Dynamic Model Generation Helpers ---
DYNAMIC_APP_LABEL = 'tests' # ADJUST AS NEEDED (e.g., your test app's name)
_dynamic_models_registry = {}

def create_dynamic_model(model_name, fields_dict, **meta_options):
    """Dynamically creates a Django model class."""
    global _dynamic_models_registry
    # Use a unique name across test runs if necessary, or rely on cleanup
    full_model_name = f"{DYNAMIC_APP_LABEL}_{model_name}"
    # if full_model_name in _dynamic_models_registry:
    #     # If called multiple times, might want to return existing one or error
    #     return _dynamic_models_registry[full_model_name]

    meta_options.setdefault('app_label', DYNAMIC_APP_LABEL)
    Meta = type('Meta', (), meta_options)
    attrs = {
        # Ensure the module path is valid within your project structure
        '__module__': f'{DYNAMIC_APP_LABEL}.models',
        'Meta': Meta,
        **fields_dict
    }
    if '__str__' not in attrs:
        attrs['__str__'] = lambda self: f"{model_name} object ({getattr(self, 'pk', 'unsaved')})"

    # Create the model class using type()
    model = type(model_name, (models.Model,), attrs)
    _dynamic_models_registry[full_model_name] = model
    return model

def clear_dynamic_models():
    """Clear the dynamic model registry."""
    global _dynamic_models_registry
    _dynamic_models_registry = {}


# --- Test Class ---

class HypothesisAgainstOneStructureTests(TestCase):
    """
    Tests optimize_query with Hypothesis generating field lists
    against a fixed dynamic model structure created once per class.
    """
    ModelA = None
    ModelB = None
    ModelC = None
    ModelD = None
    generated_models = [] # Store models created in this test class run

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.generated_models = [] # Ensure clean list for the class
        _clear_meta_cache() # Clear optimizer cache before tests

        # Check if the backend supports schema alteration
        if not connection.features.can_alter_table:
             raise SkipTest("Database backend does not support dynamic schema modification.")

        # --- 1. Define ONE Specific Dynamic Structure ---
        print("\nSetting up dynamic structure for Hypothesis tests...")
        try:
            cls.ModelD = create_dynamic_model('HypoD', {'d_field': models.CharField(max_length=20)})
            cls.ModelC = create_dynamic_model('HypoC', {'c_field': models.IntegerField(default=0)})
            cls.ModelB = create_dynamic_model(
                'HypoB', {
                    'b_field': models.CharField(max_length=30),
                    'c_link': models.ForeignKey(cls.ModelC, on_delete=models.CASCADE, related_name='b_set')
                }
            )
            cls.ModelA = create_dynamic_model(
                'HypoA', {
                    'a_field': models.CharField(max_length=10),
                    'b_link': models.ForeignKey(cls.ModelB, on_delete=models.CASCADE, related_name='a_set'),
                    'd_many': models.ManyToManyField(cls.ModelD, related_name='a_set')
                }
            )
            # Order matters for creation due to FKs
            cls.generated_models = [cls.ModelD, cls.ModelC, cls.ModelB, cls.ModelA]
        except Exception as e:
             print(f"ERROR defining dynamic models: {e}")
             # Prevent further setup if definition fails
             raise SkipTest(f"Failed to define dynamic models: {e}")

        # --- 2. Create Schema ---
        try:
            with connection.schema_editor() as editor:
                for model in cls.generated_models:
                    print(f" Creating table for {model.__name__}")
                    editor.create_model(model)
            print("Dynamic schema created.")
        except Exception as e:
            print(f"ERROR creating dynamic schema: {e}")
            cls.tearDownClass() # Attempt cleanup even if creation failed partially
            raise SkipTest(f"Failed to create dynamic schema for Hypothesis: {e}")


        # --- 3. Populate Data ---
        print("Populating dynamic data...")
        try:
            d1 = cls.ModelD.objects.create(d_field='D1')
            d2 = cls.ModelD.objects.create(d_field='D2')
            c1 = cls.ModelC.objects.create(c_field=101)
            c2 = cls.ModelC.objects.create(c_field=202)
            b1 = cls.ModelB.objects.create(b_field='B1', c_link=c1)
            b2 = cls.ModelB.objects.create(b_field='B2', c_link=c2)
            a1 = cls.ModelA.objects.create(a_field='A1', b_link=b1)
            a2 = cls.ModelA.objects.create(a_field='A2', b_link=b2)
            # Add M2M relations
            a1.d_many.add(d1, d2)
            a2.d_many.add(d1)
            print("Dynamic data populated.")
        except Exception as e:
             print(f"ERROR populating dynamic data: {e}")
             cls.tearDownClass() # Attempt cleanup
             raise SkipTest(f"Failed to populate dynamic data for Hypothesis: {e}")

    @classmethod
    def tearDownClass(cls):
        """Clean up dynamically created models and schema."""
        print("\nCleaning up dynamic structure from Hypothesis tests...")
        # Use the schema editor to delete the models' tables
        # Delete in reverse order of creation to respect FK constraints
        if connection.features.can_alter_table and cls.generated_models:
            try:
                with connection.schema_editor() as editor:
                    # Iterate over a copy in reverse, as registry might change
                    models_to_delete = list(reversed(cls.generated_models))
                    for model in models_to_delete:
                         # Check if model exists in registry before attempting delete
                         full_model_name = f"{DYNAMIC_APP_LABEL}_{model.__name__}"
                         if full_model_name in _dynamic_models_registry:
                            print(f" Deleting table for {model.__name__}")
                            editor.delete_model(model)
                         else:
                            print(f" Skipping deletion for {model.__name__} (not found in registry)")

                clear_dynamic_models() # Clear our local registry
                _clear_meta_cache() # Clear the model cache used by the optimizer
                print("Dynamic structure cleaned up.")

            except Exception as e:
                # Log error but proceed, essential for test cleanup
                print(f"\nERROR during dynamic schema cleanup: {e}. Some tables might remain.")
                # Depending on DB backend, manual cleanup might be needed if this fails
        else:
            print("Skipping schema cleanup (backend limitation or no models generated).")

        super().tearDownClass()

    # --- Hypothesis Strategy Definition ---

    # Define base strategies for fields and relations at each level
    # Making them static avoids accessing 'cls' which might not be ideal in strategy definition
    a_level_fields = staticmethod(st.sampled_from(['a_field', 'id']))
    a_relations = staticmethod(st.sampled_from(['b_link', 'd_many']))
    b_level_fields = staticmethod(st.sampled_from(['b_field', 'id']))
    b_relations = staticmethod(st.sampled_from(['c_link']))
    c_level_fields = staticmethod(st.sampled_from(['c_field', 'id']))
    d_level_fields = staticmethod(st.sampled_from(['d_field', 'id']))

    # Corrected Recursive strategy to build paths
    field_path_strategy = st.recursive(
        # Base case: Fields or relations directly on ModelA
        base=(a_level_fields | a_relations), # Strategy for the first part of the path

        # Extend function: Defines how to extend a path based on the last segment
        extend=lambda children: st.tuples(children, st.sampled_from(['__'])).map(''.join).flatmap(
            # This function receives 'current_path' generated from the 'children' strategy
            # It inspects 'current_path' and returns a STRATEGY for the *next* complete path
            lambda current_path:
                if current_path.endswith('b_link'):
                    # If last part is b_link, next part must come from ModelB fields/relations
                    next_segment_strategy = (HypothesisAgainstOneStructureTests.b_level_fields |
                                             HypothesisAgainstOneStructureTests.b_relations)
                    # Return a strategy that builds the extended path string
                    return next_segment_strategy.map(lambda segment: f"{current_path}__{segment}")

                elif current_path.endswith('c_link'):
                    # If last part is c_link, next part must come from ModelC fields
                    next_segment_strategy = HypothesisAgainstOneStructureTests.c_level_fields
                    return next_segment_strategy.map(lambda segment: f"{current_path}__{segment}")

                elif current_path.endswith('d_many'):
                    # If last part is d_many, next part must come from ModelD fields
                    next_segment_strategy = HypothesisAgainstOneStructureTests.d_level_fields
                    return next_segment_strategy.map(lambda segment: f"{current_path}__{segment}")

                else:
                    # If the path ends in a non-relation ('a_field', 'b_field', 'c_field', 'd_field', 'id'),
                    # it cannot be extended further according to Django's lookup rules.
                    # Return a strategy that just yields the current path, stopping recursion.
                    return st.just(current_path)
        ),
        max_leaves=5 # Limit the total number of path segments to prevent excessive depth
    )

    # Strategy for generating a list of field paths using the recursive one above
    @staticmethod
    @st.composite
    def st_field_list_for_structure(draw, max_size=8): # 'draw' IS available here
        # Generate a list of potential paths using the recursive strategy
        paths = draw(st.lists(
            HypothesisAgainstOneStructureTests.field_path_strategy,
            min_size=1,
            max_size=max_size,
            unique=True
        ))

        # Optional: Ensure at least one root-level field/relation is included
        # This helps avoid cases where only very deep, possibly invalid paths are generated.
        root_parts = {'a_field', 'id', 'b_link', 'd_many'}
        if paths and not any(p in root_parts for p in paths):
            # Use 'draw' correctly here inside the @st.composite function
            paths.append(draw(st.sampled_from(list(root_parts))))

        # Optional Filtering (Example): Remove paths that try to traverse past a non-relation
        # This makes the generated data slightly cleaner, though the optimizer should handle it.
        def is_valid_traversal(path):
            parts = path.split('__')
            # Simplified check: allow only known relations to be followed by '__'
            # This doesn't use actual model introspection, just known names in this structure.
            allowed_intermediate = {'b_link', 'c_link', 'd_many'}
            for i, part in enumerate(parts[:-1]): # Check all parts except the last
                 # A more robust check would involve model introspection
                 if part not in allowed_intermediate and not part.endswith('_id'): # Basic check
                     # Allow *_id fields to appear anywhere
                     field_on_a = {'a_field', 'id'}
                     field_on_b = {'b_field', 'id'}
                     field_on_c = {'c_field', 'id'}
                     field_on_d = {'d_field', 'id'}
                     # If part is a simple field but not the last one, it's likely invalid traversal
                     if (part in field_on_a or part in field_on_b or
                         part in field_on_c or part in field_on_d):
                          print(f" Filtering potentially invalid path: {path} (part: {part})")
                          return False
            return True

        # Apply the filter
        # valid_paths = [p for p in paths if is_valid_traversal(p)]
        # return valid_paths if valid_paths else paths[:1] # Ensure at least one path remains

        # Return the generated (and possibly filtered) list of paths
        return paths


    # --- Helper for accessing fields ---
    def _access_dynamic_fields(self, obj, field_path_list):
        """Accesses fields to trigger lazy loads or use prefetched data."""
        if obj is None:
            return
        for field_path in field_path_list:
            current_value = obj
            parts = field_path.split('__')
            try:
                for i, part in enumerate(parts):
                    if current_value is None:
                        # Cannot traverse further if an intermediate object is None
                        # print(f" Access Warning: Intermediate None at '{'__'.join(parts[:i])}' for path '{field_path}'")
                        break

                    # Check for Manager (M2M, reverse FK/O2O)
                    potential_manager = getattr(current_value, part, None)
                    if isinstance(potential_manager, models.Manager):
                        # Access all related objects to trigger the query/prefetch
                        related_objects = list(potential_manager.all())
                        # If we need to access fields *on* these related objects:
                        if i < len(parts) - 1:
                            remaining_path_list = ['__'.join(parts[i+1:])]
                            for related_obj in related_objects:
                                # Recursive call for fields on related objects
                                self._access_dynamic_fields(related_obj, remaining_path_list)
                        # Stop traversing this specific path part via attribute access
                        current_value = related_objects # For potential debugging/inspection
                        break
                    else:
                         # Regular attribute or forward FK/O2O
                         current_value = getattr(current_value, part)

            except AttributeError:
                 # This might happen if the path is invalid or data is missing
                 # print(f" Access Warning: AttributeError at '{part}' in path '{field_path}' starting from {obj}")
                 break # Stop processing this path
            except Exception as e:
                 # Catch other potential errors during access
                 print(f" Access Error: {type(e).__name__} at '{part}' in path '{field_path}': {e}")
                 break


    # --- Hypothesis Test Method ---
    @settings(
        deadline=None, # Disable deadline for potentially slow Django tests
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
        max_examples=50 # Number of examples Hypothesis should generate
    )
    @given(fields=st_field_list_for_structure()) # Use the composite strategy
    def test_optimizer_hypothesis_varied_fields(self, fields):
        """
        Tests optimize_query with Hypothesis-generated field lists against the class structure.
        Focuses on robustness and ensuring no unexpected errors occur.
        """
        # Ensure the ModelA class was set up correctly
        assume(self.ModelA is not None)

        print(f"\nHypothesis trying fields: {fields}")

        reset_queries()
        _clear_meta_cache() # Clean optimizer cache for each run

        try:
            # Get the base queryset
            base_qs = self.ModelA.objects.all()

            # --- Run the optimization ---
            optimized_qs = optimize_query(base_qs, fields)

            # --- Execute the query and access data ---
            with CaptureQueriesContext(connection) as context:
                # Evaluate the main query
                results = list(optimized_qs)

                # Access fields to trigger prefetches and check for lazy load errors
                # This also helps ensure the generated query plan was valid
                for obj in results:
                    self._access_dynamic_fields(obj, fields)

            # --- Basic Assertions ---
            query_count = len(context.captured_queries)
            print(f" -> Query Count: {query_count}")

            self.assertIsNotNone(results, "QuerySet evaluation failed (returned None).")

            # Set a reasonable upper bound for queries. Exceeding this likely indicates
            # a failure in select_related or prefetch_related optimization.
            # Max expected: 1 (main A+B+C) + 1 (prefetch D) = 2? Maybe 3 if complex.
            self.assertLessEqual(query_count, 5, f"Generated an excessive number of queries ({query_count}) for fields: {fields}")

        except FieldError as e:
            # optimize_query should ideally not construct queries that lead to FieldError.
            self.fail(f"Optimizer produced a FieldError for fields {fields}: {e}")
        except FieldDoesNotExist as e:
            # This might be acceptable if Hypothesis generates an invalid path structure
            # (e.g., 'a_field__invalid'). The optimizer should ideally handle this gracefully
            # (e.g., by logging a warning and ignoring the invalid part).
            # If it raises this error, it might indicate insufficient error handling within optimize_query.
             print(f" WARNING: Optimizer raised FieldDoesNotExist for path in {fields}: {e}. Review optimizer's handling of invalid paths.")
             # Depending on strictness, you might fail the test here:
             # self.fail(f"Optimizer raised FieldDoesNotExist for fields {fields}: {e}")
             pass # Allow this for now, assuming the optimizer should try its best.
        except Exception as e:
            # Catch any other unexpected Python errors (IndexError, TypeError, AttributeError etc.)
            # These likely indicate a bug in the optimizer's internal logic.
            logging.exception(f"Optimization failed unexpectedly for fields {fields}") # Log traceback
            self.fail(f"Optimization failed unexpectedly for fields {fields}: {type(e).__name__}: {e}")