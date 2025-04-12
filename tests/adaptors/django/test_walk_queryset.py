import unittest
from django.test import TestCase
from django.db.models import Count, Prefetch
from django.db import connection
from django.test.utils import CaptureQueriesContext

# Import the function we're testing
from statezero.adaptors.django.helpers import collect_models_by_type, collect_from_queryset
from statezero.adaptors.django.query_optimizer import DjangoQueryOptimizer
from statezero.adaptors.django.config import config

from tests.django_app.models import (
     DeepModelLevel1, DeepModelLevel2, DeepModelLevel3,
     DummyModel, DummyRelatedModel, ComprehensiveModel
 )

class ModelCollectorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create test data
        # Level 3
        cls.level3_1 = DeepModelLevel3.objects.create(name="level3_1")
        cls.level3_2 = DeepModelLevel3.objects.create(name="level3_2")
        
        # Level 2
        cls.level2_1 = DeepModelLevel2.objects.create(name="level2_1", level3=cls.level3_1)
        cls.level2_2 = DeepModelLevel2.objects.create(name="level2_2", level3=cls.level3_2)
        
        # Level 1
        cls.level1_1 = DeepModelLevel1.objects.create(name="level1_1", level2=cls.level2_1)
        cls.level1_2 = DeepModelLevel1.objects.create(name="level1_2", level2=cls.level2_2)
        
        # Comprehensive models
        cls.comp1 = ComprehensiveModel.objects.create(
            char_field="comp1",
            text_field="Text for comp1",
            int_field=42,
            decimal_field=10.5,
            json_field={"key": "value"}
        )
        cls.comp2 = ComprehensiveModel.objects.create(
            char_field="comp2",
            text_field="Text for comp2",
            int_field=84,
            decimal_field=20.75,
            json_field={"another_key": "another_value"}
        )
        
        # Connect comprehensive models to level1 models
        cls.level1_1.comprehensive_models.add(cls.comp1)
        cls.level1_2.comprehensive_models.add(cls.comp2)
        
        # Dummy related model
        cls.dummy_related = DummyRelatedModel.objects.create(name="dummy_related")
        
        # Dummy model
        cls.dummy = DummyModel.objects.create(
            name="dummy",
            value=100,
            related=cls.dummy_related
        )
        
        # Generate consistent model names using the ORM provider
        cls.MODEL_NAMES = {
            DeepModelLevel1: config.orm_provider.get_model_name(DeepModelLevel1),
            DeepModelLevel2: config.orm_provider.get_model_name(DeepModelLevel2),
            DeepModelLevel3: config.orm_provider.get_model_name(DeepModelLevel3),
            ComprehensiveModel: config.orm_provider.get_model_name(ComprehensiveModel),
            DummyModel: config.orm_provider.get_model_name(DummyModel),
            DummyRelatedModel: config.orm_provider.get_model_name(DummyRelatedModel),
        }

    def test_collect_single_model_instance(self):
        """Test collecting a single model instance."""
        fields_map = {
            self.MODEL_NAMES[DeepModelLevel1]: {"name"},
        }
        
        collected = collect_from_queryset(
            self.level1_1, 
            fields_map,
            get_model_name=config.orm_provider.get_model_name,
            get_model=config.orm_provider.get_model_by_name
        )
        
        # Check that we have the right model type
        self.assertIn(self.MODEL_NAMES[DeepModelLevel1], collected)
        
        # Check that we have the correct instance
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel1]]), 1)
        self.assertEqual(collected[self.MODEL_NAMES[DeepModelLevel1]][0].id, self.level1_1.id)

    def test_collect_queryset(self):
        """Test collecting from a queryset."""
        fields_map = {
            self.MODEL_NAMES[DeepModelLevel1]: {"name"},
        }
        
        queryset = DeepModelLevel1.objects.all()
        collected = collect_from_queryset(
            queryset, 
            fields_map,
            get_model_name=config.orm_provider.get_model_name,
            get_model=config.orm_provider.get_model_by_name
        )
        
        # Check that we have the right model type
        self.assertIn(self.MODEL_NAMES[DeepModelLevel1], collected)
        
        # Check that we have all the instances
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel1]]), 2)
        ids = {obj.id for obj in collected[self.MODEL_NAMES[DeepModelLevel1]]}
        self.assertEqual(ids, {self.level1_1.id, self.level1_2.id})

    def test_collect_with_foreign_key(self):
        """Test collecting with a foreign key relationship."""
        fields_map = {
            self.MODEL_NAMES[DeepModelLevel1]: {"name", "level2"},
            self.MODEL_NAMES[DeepModelLevel2]: {"name"},
        }
        
        # Get a queryset with select_related
        queryset = DeepModelLevel1.objects.select_related("level2").all()
        
        # Count SQL queries
        with CaptureQueriesContext(connection) as queries:
            collected = collect_from_queryset(
                queryset, 
                fields_map,
                get_model_name=config.orm_provider.get_model_name,
                get_model=config.orm_provider.get_model_by_name
            )
        
        # Check that we collected both model types
        self.assertIn(self.MODEL_NAMES[DeepModelLevel1], collected)
        self.assertIn(self.MODEL_NAMES[DeepModelLevel2], collected)
        
        # Check that we have all level1 instances
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel1]]), 2)
        
        # Check that we have all level2 instances 
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel2]]), 2)
        level2_ids = {obj.id for obj in collected[self.MODEL_NAMES[DeepModelLevel2]]}
        self.assertEqual(level2_ids, {self.level2_1.id, self.level2_2.id})
        
        # Since we used select_related, we should only have 1 database query
        # (the initial query to get level1 with level2)
        self.assertEqual(len(queries), 1)

    def test_collect_with_deeper_relationships(self):
        """Test collecting with deeper relationships."""
        fields_map = {
            self.MODEL_NAMES[DeepModelLevel1]: {"name", "level2"},
            self.MODEL_NAMES[DeepModelLevel2]: {"name", "level3"},
            self.MODEL_NAMES[DeepModelLevel3]: {"name"},
        }
        
        # Get a queryset with select_related for deeper relationships
        queryset = DeepModelLevel1.objects.select_related("level2__level3").all()
        
        # Count SQL queries
        with CaptureQueriesContext(connection) as queries:
            collected = collect_from_queryset(
                queryset, 
                fields_map,
                get_model_name=config.orm_provider.get_model_name,
                get_model=config.orm_provider.get_model_by_name
            )
        
        # Check that we collected all three model types
        self.assertIn(self.MODEL_NAMES[DeepModelLevel1], collected)
        self.assertIn(self.MODEL_NAMES[DeepModelLevel2], collected)
        self.assertIn(self.MODEL_NAMES[DeepModelLevel3], collected)
        
        # Check that we have all level3 instances
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel3]]), 2)
        level3_ids = {obj.id for obj in collected[self.MODEL_NAMES[DeepModelLevel3]]}
        self.assertEqual(level3_ids, {self.level3_1.id, self.level3_2.id})
        
        # Since we used select_related, we should only have 1 database query
        self.assertEqual(len(queries), 1)

    def test_collect_with_many_to_many(self):
        """Test collecting with many-to-many relationships."""
        fields_map = {
            self.MODEL_NAMES[DeepModelLevel1]: {"name", "comprehensive_models"},
            self.MODEL_NAMES[ComprehensiveModel]: {"char_field", "int_field"},
        }
        
        # Get a queryset with prefetch_related for the many-to-many
        queryset = DeepModelLevel1.objects.prefetch_related("comprehensive_models").all()
        
        # Count SQL queries
        with CaptureQueriesContext(connection) as queries:
            collected = collect_from_queryset(
                queryset, 
                fields_map,
                get_model_name=config.orm_provider.get_model_name,
                get_model=config.orm_provider.get_model_by_name
            )
        
        # Check that we collected both model types
        self.assertIn(self.MODEL_NAMES[DeepModelLevel1], collected)
        self.assertIn(self.MODEL_NAMES[ComprehensiveModel], collected)
        
        # Check that we have all comprehensive models
        self.assertEqual(len(collected[self.MODEL_NAMES[ComprehensiveModel]]), 2)
        comp_fields = {obj.char_field for obj in collected[self.MODEL_NAMES[ComprehensiveModel]]}
        self.assertEqual(comp_fields, {"comp1", "comp2"})
        
        # We should have 2 queries: one for level1 and one for the prefetched comprehensive_models
        self.assertEqual(len(queries), 2)

    def test_collect_complex_query(self):
        """Test collecting with a complex query involving multiple relationships."""
        fields_map = {
            self.MODEL_NAMES[DeepModelLevel1]: {"name", "level2", "comprehensive_models"},
            self.MODEL_NAMES[DeepModelLevel2]: {"name", "level3"},
            self.MODEL_NAMES[DeepModelLevel3]: {"name"},
            self.MODEL_NAMES[ComprehensiveModel]: {"char_field", "int_field"},
        }
        
        # Get a queryset with both select_related and prefetch_related
        queryset = (
            DeepModelLevel1.objects
            .select_related("level2__level3")
            .prefetch_related("comprehensive_models")
            .all()
        )
        
        # Count SQL queries
        with CaptureQueriesContext(connection) as queries:
            collected = collect_from_queryset(
                queryset, 
                fields_map,
                get_model_name=config.orm_provider.get_model_name,
                get_model=config.orm_provider.get_model_by_name
            )
        
        # Check that we collected all model types
        self.assertIn(self.MODEL_NAMES[DeepModelLevel1], collected)
        self.assertIn(self.MODEL_NAMES[DeepModelLevel2], collected)
        self.assertIn(self.MODEL_NAMES[DeepModelLevel3], collected)
        self.assertIn(self.MODEL_NAMES[ComprehensiveModel], collected)
        
        # Check model counts
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel1]]), 2)
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel2]]), 2)
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel3]]), 2)
        self.assertEqual(len(collected[self.MODEL_NAMES[ComprehensiveModel]]), 2)
        
        # We should have 2 queries: one for level1 with level2/level3, one for comprehensive_models
        self.assertEqual(len(queries), 2)

    def test_collect_with_query_optimization(self):
        """Test that our collector works with the DjangoQueryOptimizer."""
        # Create fields map for the optimizer
        fields_map = {
            self.MODEL_NAMES[DeepModelLevel1]: {"name", "level2", "comprehensive_models"},
            self.MODEL_NAMES[DeepModelLevel2]: {"name", "level3"},
            self.MODEL_NAMES[DeepModelLevel3]: {"name"},
            self.MODEL_NAMES[ComprehensiveModel]: {"char_field", "int_field"},
        }
        
        # Use the query optimizer to optimize the queryset
        optimizer = DjangoQueryOptimizer(
            depth=2,
            fields_per_model=fields_map,
            get_model_name_func=config.orm_provider.get_model_name
        )
        
        # Get the base queryset
        queryset = DeepModelLevel1.objects.all()
        
        # Apply optimization
        optimized_queryset = optimizer.optimize(queryset)
        
        # Count SQL queries when using the optimized queryset
        with CaptureQueriesContext(connection) as queries:
            collected = collect_from_queryset(
                optimized_queryset, 
                fields_map,
                get_model_name=config.orm_provider.get_model_name,
                get_model=config.orm_provider.get_model_by_name
            )
        
        # Check that we collected all model types
        self.assertIn(self.MODEL_NAMES[DeepModelLevel1], collected)
        self.assertIn(self.MODEL_NAMES[DeepModelLevel2], collected)
        self.assertIn(self.MODEL_NAMES[DeepModelLevel3], collected)
        self.assertIn(self.MODEL_NAMES[ComprehensiveModel], collected)
        
        # Check model counts
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel1]]), 2)
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel2]]), 2)
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel3]]), 2)
        self.assertEqual(len(collected[self.MODEL_NAMES[ComprehensiveModel]]), 2)
        
        # We should have a minimal number of queries due to optimization
        # Exact number depends on the optimizer implementation
        self.assertLessEqual(len(queries), 3)

    def test_model_name_case_insensitivity(self):
        """Test that model name matching is case-insensitive."""
        # Get the correct model name
        level1_name = self.MODEL_NAMES[DeepModelLevel1]
        level2_name = self.MODEL_NAMES[DeepModelLevel2]
        
        # Create a fields map with altered case
        fields_map = {
            level1_name.lower(): {"name", "level2"},
            level2_name.upper(): {"name"},
        }
        
        # Get a queryset with select_related
        queryset = DeepModelLevel1.objects.select_related("level2").all()
        
        collected = collect_from_queryset(
            queryset, 
            fields_map,
            get_model_name=config.orm_provider.get_model_name,
            get_model=config.orm_provider.get_model_by_name
        )
        
        # Should still find the correct models despite case difference
        self.assertIn(level1_name.lower(), collected)
        self.assertIn(level2_name.upper(), collected)
        
        # Check that we have all expected instances
        self.assertEqual(len(collected[level1_name.lower()]), 2)
        self.assertEqual(len(collected[level2_name.upper()]), 2)

    def test_cycle_prevention(self):
        """Test that the collector prevents infinite recursion with circular references."""
        # Create a circular reference
        self.comp1.related = self.level1_1
        self.comp1.save()
        
        fields_map = {
            self.MODEL_NAMES[DeepModelLevel1]: {"name", "comprehensive_models"},
            self.MODEL_NAMES[ComprehensiveModel]: {"char_field", "related"},
        }
        
        # This should not cause infinite recursion
        queryset = DeepModelLevel1.objects.prefetch_related("comprehensive_models").all()
        
        collected = collect_from_queryset(
            queryset, 
            fields_map,
            get_model_name=config.orm_provider.get_model_name,
            get_model=config.orm_provider.get_model_by_name
        )
        
        # Both model types should be collected
        self.assertIn(self.MODEL_NAMES[DeepModelLevel1], collected)
        self.assertIn(self.MODEL_NAMES[ComprehensiveModel], collected)
        
        # Each instance should be collected exactly once
        level1_ids = {obj.id for obj in collected[self.MODEL_NAMES[DeepModelLevel1]]}
        self.assertEqual(len(level1_ids), 2)
        self.assertEqual(level1_ids, {self.level1_1.id, self.level1_2.id})

    def test_collect_complex_query_with_debug(self):
        """Test collecting with a complex query involving multiple relationships, with debug output."""
        print("\n==== STARTING DEBUG TEST ====")
        
        # Print model names from ORM provider for reference
        print(f"DeepModelLevel1 name: {self.MODEL_NAMES[DeepModelLevel1]}")
        print(f"DeepModelLevel2 name: {self.MODEL_NAMES[DeepModelLevel2]}")
        print(f"DeepModelLevel3 name: {self.MODEL_NAMES[DeepModelLevel3]}")
        print(f"ComprehensiveModel name: {self.MODEL_NAMES[ComprehensiveModel]}")
        
        fields_map = {
            self.MODEL_NAMES[DeepModelLevel1]: {"name", "level2", "comprehensive_models"},
            self.MODEL_NAMES[DeepModelLevel2]: {"name", "level3"},
            self.MODEL_NAMES[DeepModelLevel3]: {"name"},
            self.MODEL_NAMES[ComprehensiveModel]: {"char_field", "int_field"},
        }
        
        print("\nFields map:")
        for model_name, fields in fields_map.items():
            print(f"  {model_name}: {fields}")
        
        # Get a queryset with both select_related and prefetch_related
        queryset = (
            DeepModelLevel1.objects
            .select_related("level2__level3")
            .prefetch_related("comprehensive_models")
            .all()
        )
        
        # Print the SQL query that will be executed
        print(f"\nQueryset SQL: {queryset.query}")
        
        # Count SQL queries
        with CaptureQueriesContext(connection) as queries:
            collected = collect_from_queryset(
                queryset, 
                fields_map,
                get_model_name=config.orm_provider.get_model_name,
                get_model=config.orm_provider.get_model_by_name
            )
            
            # Print the executed SQL queries
            print("\nExecuted queries:")
            for i, query in enumerate(queries):
                print(f"  Query {i+1}: {query['sql'][:200]}...")
        
        # Print the collected models and their counts
        print("\nCollected model types:")
        for model_type, instances in collected.items():
            print(f"  {model_type}: {len(instances)} instances")
            print(f"    IDs: {[obj.id for obj in instances]}")
            # Print a sample of the first instance's attributes
            if instances:
                first_instance = instances[0]
                print(f"    Sample attributes for first instance (ID {first_instance.id}):")
                if model_type == self.MODEL_NAMES[DeepModelLevel1]:
                    print(f"      name: {first_instance.name}")
                    print(f"      level2.id: {first_instance.level2.id}")
                    print(f"      level2.name: {first_instance.level2.name}")
                    print(f"      level2.level3.id: {first_instance.level2.level3.id}")
                    print(f"      level2.level3.name: {first_instance.level2.level3.name}")
                    cms = list(first_instance.comprehensive_models.all())
                    print(f"      comprehensive_models count: {len(cms)}")
                    if cms:
                        print(f"      first comprehensive_model.char_field: {cms[0].char_field}")
                elif model_type == self.MODEL_NAMES[DeepModelLevel2]:
                    print(f"      name: {first_instance.name}")
                    print(f"      level3.id: {first_instance.level3.id}")
                    print(f"      level3.name: {first_instance.level3.name}")
                elif model_type == self.MODEL_NAMES[DeepModelLevel3]:
                    print(f"      name: {first_instance.name}")
                elif model_type == self.MODEL_NAMES[ComprehensiveModel]:
                    print(f"      char_field: {first_instance.char_field}")
                    print(f"      int_field: {first_instance.int_field}")
        
        # Verify that the correct models were collected
        for model_type in [
            self.MODEL_NAMES[DeepModelLevel1],
            self.MODEL_NAMES[DeepModelLevel2],
            self.MODEL_NAMES[DeepModelLevel3],
            self.MODEL_NAMES[ComprehensiveModel]
        ]:
            self.assertIn(model_type, collected)
        
        # Check model counts
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel1]]), 2)
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel2]]), 2)
        self.assertEqual(len(collected[self.MODEL_NAMES[DeepModelLevel3]]), 2)
        self.assertEqual(len(collected[self.MODEL_NAMES[ComprehensiveModel]]), 2)
        
        # We should have 2 queries: one for level1 with level2/level3, one for comprehensive_models
        self.assertEqual(len(queries), 2)
        
        print("\n==== END DEBUG TEST ====")

if __name__ == "__main__":
    unittest.main()