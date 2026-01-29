import time
from django.test import TestCase
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.db.models import Q

from tests.django_app.models import (
    Product, ProductCategory, Order, OrderItem,
    DeepModelLevel1, DeepModelLevel2, DeepModelLevel3,
    ComprehensiveModel, DailyRate, RatePlan
)

# Update imports to include DjangoQueryOptimizer
from statezero.adaptors.django.query_optimizer import DjangoQueryOptimizer

class QueryOptimizerTests(TestCase):
    """Tests for the query optimizer covering various scenarios."""
    
    @classmethod
    def setUpTestData(cls):
        """Create test data for all tests."""
        # Create categories
        for i in range(3):
            category = ProductCategory.objects.create(name=f"Category {i}")
            
            # Create products in each category
            for j in range(3):
                Product.objects.create(
                    name=f"Product {i}-{j}",
                    description=f"Description for product {i}-{j}",
                    price=10 * (i + 1) + j,
                    category=category
                )
        
        # Create deep models
        for i in range(2):
            level3 = DeepModelLevel3.objects.create(name=f"Level3 {i}")
            
            for j in range(2):
                level2 = DeepModelLevel2.objects.create(
                    name=f"Level2 {i}-{j}",
                    level3=level3
                )
                
                level1 = DeepModelLevel1.objects.create(
                    name=f"Level1 {i}-{j}",
                    level2=level2
                )
                
                # Create related comprehensive model
                comp_model = ComprehensiveModel.objects.create(
                    char_field=f"Comp {i}-{j}",
                    text_field=f"Text for comp {i}-{j}",
                    int_field=i * 100 + j * 10,
                    decimal_field=i + j + 0.5,
                    bool_field=True,
                    # Fix for datetime_field NULL constraint
                    datetime_field=timezone.now(),
                    json_field={"key": f"value-{i}-{j}"},
                    money_field=i * 10 + j,
                    related=level1
                )
                
                # Setup many-to-many relationship
                level1.comprehensive_models.add(comp_model)
        
        # Create orders
        for i in range(3):
            order = Order.objects.create(
                order_number=f"ORD-{i:03d}",
                customer_name=f"Customer {i}",
                customer_email=f"customer{i}@example.com",
                total=0
            )
            
            # Add items to order
            products = list(Product.objects.all()[:3])
            total = 0
            for j, product in enumerate(products):
                quantity = j + 1
                price = float(product.price)
                
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    price=price
                )
                
                total += price * quantity
            
            # Update order total
            order.total = total
            order.save()
        
        cls.get_model_name = lambda model: model.__name__
    
    def _test_optimization(self, model, fields, expected_max_queries, description, generate_paths_mode=False, depth=2, specific_fields=None, filter_condition=None, q_filter=None):
        """
        Shared test logic for all optimization tests.
        
        Tests:
        1. Query count is reduced
        2. Performance is improved 
        3. Results are identical (both IDs and count)
        
        Args:
            model: The model class to query
            fields: List of fields to optimize for
            expected_max_queries: Maximum number of queries expected after optimization
            description: Description of the test for logging
            generate_paths_mode: Whether to use generate_paths mode
            depth: Depth for generate_paths
            specific_fields: Fields per model for generate_paths
            filter_condition: Optional filter condition as a dict
            q_filter: Optional Q object filter
        """
        # Create base queryset with filtering if provided
        base_queryset = model.objects.all()
        if filter_condition:
            base_queryset = base_queryset.filter(**filter_condition)
        if q_filter:
            base_queryset = base_queryset.filter(q_filter)
            
        # Get baseline results for comparison
        baseline_ids = list(base_queryset.values_list('id', flat=True))
        baseline_count = len(baseline_ids)
        
        # Test unoptimized query
        reset_queries()
        start_time = time.time()
        with CaptureQueriesContext(connection) as context:
            # Get all objects
            objects = list(base_queryset)
            
            # Access fields to trigger lazy loading
            for obj in objects:
                self._access_fields(obj, fields)
                
            unoptimized_query_count = len(context.captured_queries)
        unoptimized_time = time.time() - start_time
        
        # Test optimized query
        reset_queries()
        start_time = time.time()
        with CaptureQueriesContext(connection) as context:
            # Create a new optimizer instance for each test
            optimizer = DjangoQueryOptimizer(
                depth=depth,
                fields_per_model=specific_fields,
                get_model_name_func=self.get_model_name,
                use_only=True
            )
            
            # Optimize the query
            if generate_paths_mode:
                optimized_qs = optimizer.optimize(
                    base_queryset
                )
            else:
                optimized_qs = optimizer.optimize(
                    base_queryset,
                    fields=fields
                )

            objects = list(optimized_qs)
            optimized_count = len(objects)
            
            # Access the same fields
            for obj in objects:
                self._access_fields(obj, fields)
                
            optimized_query_count = len(context.captured_queries)
        optimized_time = time.time() - start_time
        
        # Get optimized query results for comparison
        optimized_ids = list(optimized_qs.values_list('id', flat=True))
        
        # Print performance metrics
        filter_info = ""
        if filter_condition or q_filter:
            filter_info = " with filtering"
        
        print(f"\n{description}{filter_info} Results:")
        print(f"Row count: {optimized_count}")
        print(f"Unoptimized: {unoptimized_query_count} queries, {unoptimized_time:.4f}s")
        print(f"Optimized: {optimized_query_count} queries, {optimized_time:.4f}s")
        print(f"Query reduction: {unoptimized_query_count - optimized_query_count} queries ({(1 - optimized_query_count / unoptimized_query_count) * 100:.1f}%)")
        print(f"Time reduction: {(1 - optimized_time / unoptimized_time) * 100:.1f}%")
        
        # Assertions
        # 1. Query count is reduced
        self.assertLess(
            optimized_query_count, unoptimized_query_count,
            f"Expected fewer queries for optimized ({optimized_query_count}) vs unoptimized ({unoptimized_query_count})"
        )
        
        # 2. Should have at most the expected number of queries
        self.assertLessEqual(
            optimized_query_count, expected_max_queries,
            f"Expected at most {expected_max_queries} queries, got {optimized_query_count}"
        )
        
        # 3. Results should be identical (IDs)
        self.assertEqual(
            optimized_ids, baseline_ids,
            "Optimized query returned different results than baseline"
        )
        
        # 4. Row counts should be identical
        self.assertEqual(
            optimized_count, baseline_count,
            f"Optimized query returned different number of rows ({optimized_count}) than baseline ({baseline_count})"
        )
        
        # 5. Time should be better or at least not significantly worse
        # (Using a tolerance factor since timing can vary)
        self.assertLessEqual(
            optimized_time, unoptimized_time * 1.2,
            f"Optimized query took significantly longer ({optimized_time:.4f}s) than unoptimized ({unoptimized_time:.4f}s)"
        )
    
    def _access_fields(self, obj, fields):
        """Access all specified fields on an object."""
        for field in fields:
            parts = field.split('__')
            
            # Navigate through the field parts
            value = obj
            for part in parts:
                if hasattr(value, part):
                    value = getattr(value, part)
                elif hasattr(value, 'all') and callable(value.all):
                    # Handle M2M relationships
                    value = list(value.all())
                    if value and len(parts) > 1:
                        # For each related object, get the remaining field
                        remaining_field = '__'.join(parts[parts.index(part)+1:])
                        for related_obj in value:
                            self._access_field(related_obj, remaining_field)
                        break
    
    def _access_field(self, obj, field_path):
        """Helper to access a field path on an object."""
        if not field_path:
            return
            
        parts = field_path.split('__')
        
        value = obj
        for part in parts:
            if hasattr(value, part):
                value = getattr(value, part)
            elif hasattr(value, 'all') and callable(value.all):
                # Handle M2M relationships
                value = list(value.all())
                if value and len(parts) > 1:
                    # For each related object, get the remaining field
                    for related_obj in value:
                        remaining_field = '__'.join(parts[parts.index(part)+1:])
                        self._access_field(related_obj, remaining_field)
                    break
    
    def test_select_related_heavy(self):
        """Test with heavy use of select_related (foreign keys)."""
        fields = [
            'name',
            'category__name',
            'category__id'
        ]
        self._test_optimization(
            Product, 
            fields, 
            expected_max_queries=1,
            description="Select-Related Heavy"
        )
    
    def test_prefetch_related_heavy(self):
        """Test with heavy use of prefetch_related (many-to-many)."""
        fields = [
            'name',
            'comprehensive_models__char_field',
            'comprehensive_models__text_field',
            'comprehensive_models__int_field'
        ]
        self._test_optimization(
            DeepModelLevel1, 
            fields, 
            expected_max_queries=2,  # Main query + prefetch query
            description="Prefetch-Related Heavy"
        )
    
    def test_deep_nested_foreign_keys(self):
        """Test with deeply nested foreign key relationships."""
        fields = [
            'name',
            'level2__name',
            'level2__level3__name'
        ]
        self._test_optimization(
            DeepModelLevel1, 
            fields, 
            expected_max_queries=1,
            description="Deep Nested Foreign Keys"
        )
    
    def test_nested_mixed_relationships(self):
        """Test with a mix of select_related and prefetch_related."""
        fields = [
            'name',
            'level2__name',
            'level2__level3__name',
            'comprehensive_models__char_field',
            'comprehensive_models__int_field'
        ]
        self._test_optimization(
            DeepModelLevel1, 
            fields, 
            expected_max_queries=3,  # Main query + nested selects + prefetch
            description="Nested Mixed Relationships"
        )
    
    def test_multiple_levels_of_prefetch(self):
        """Test with multiple levels of prefetch_related."""
        fields = [
            'order_number',
            'items__quantity',
            'items__product__name',
            'items__product__category__name'
        ]
        self._test_optimization(
            Order, 
            fields, 
            expected_max_queries=4,  # Main + items + products + categories
            description="Multiple Levels of Prefetch"
        )
    
    def test_basic_filtering(self):
        """Test optimization with basic field filtering."""
        fields = [
            'name',
            'price',
            'category__name'
        ]
        
        filter_condition = {'price__gt': 20}
        
        self._test_optimization(
            Product, 
            fields, 
            expected_max_queries=1,
            description="Basic Filtering",
            filter_condition=filter_condition
        )
    
    def test_q_object_filtering(self):
        """Test optimization with Q object filtering."""
        fields = [
            'name',
            'price',
            'category__name'
        ]
        
        # Create a complex Q filter
        q_filter = Q(price__lt=15) | Q(name__contains='1')
        
        self._test_optimization(
            Product, 
            fields, 
            expected_max_queries=1,
            description="Q Object Filtering",
            q_filter=q_filter
        )
    
    def test_complex_filtering(self):
        """Test optimization with both basic and Q object filtering."""
        fields = [
            'name',
            'price',
            'category__name'
        ]
        
        # Combine both filter types
        filter_condition = {'category__name__contains': 'Category'}
        q_filter = Q(price__gt=15) | Q(name__contains='2')
        
        self._test_optimization(
            Product, 
            fields, 
            expected_max_queries=1,
            description="Complex Filtering",
            filter_condition=filter_condition,
            q_filter=q_filter
        )
    
    def test_filtering_with_optimization(self):
        """Test that optimization works with filtering."""
        fields = [
            'name',
            'price',
            'category__name'
        ]

        fields_map = {
            'Product': ['name', 'price', 'id'],
            'Category': ['name', 'id']
        }
        
        # Create a filtered queryset
        filtered_qs = Product.objects.filter(price__gt=20)
        filtered_ids = list(filtered_qs.values_list('id', flat=True))
        filtered_count = len(filtered_ids)
        
        # Test unoptimized
        reset_queries()
        start_time = time.time()
        with CaptureQueriesContext(connection) as context:
            objects = list(filtered_qs)
            unoptimized_count = len(objects)
            for obj in objects:
                _ = obj.category.name
            unoptimized_query_count = len(context.captured_queries)
        unoptimized_time = time.time() - start_time
        
        # Test optimized
        reset_queries()
        start_time = time.time()
        with CaptureQueriesContext(connection) as context:
            # Create a new optimizer instance
            optimizer = DjangoQueryOptimizer(
                fields_per_model=fields_map,
                get_model_name_func=self.get_model_name,
                use_only=True
            )
            
            # Use the optimizer instance
            optimized_qs = optimizer.optimize(
                filtered_qs, 
                fields=fields
            )
            objects = list(optimized_qs)
            optimized_count = len(objects)
            
            for obj in objects:
                _ = obj.category.name
            optimized_query_count = len(context.captured_queries)
        optimized_time = time.time() - start_time
        
        # Get results
        optimized_ids = list(optimized_qs.values_list('id', flat=True))
        
        # Print metrics
        print(f"\nFiltering with Optimization Results:")
        print(f"Row count: {optimized_count}")
        print(f"Unoptimized: {unoptimized_query_count} queries, {unoptimized_time:.4f}s")
        print(f"Optimized: {optimized_query_count} queries, {optimized_time:.4f}s")
        
        # Assertions
        self.assertLessEqual(optimized_query_count, unoptimized_query_count)
        self.assertEqual(optimized_ids, filtered_ids)
        self.assertEqual(optimized_count, filtered_count)
        self.assertEqual(optimized_count, unoptimized_count)

    def test_generate_paths_select_related(self):
        """Test generate_paths function with select_related scenario."""

        specific_fields = {
            "Product": ["name", "price", "category"],
            "ProductCategory": ["name", "id"]
        }
        self._test_optimization(
            Product,
            fields=['name', 'price', 'category__name', 'category__id'],  # Original fields for comparison
            expected_max_queries=1,
            description="Generate Paths Select-Related",
            generate_paths_mode=True,
            depth=2,
            specific_fields=specific_fields
        )

    def test_generate_paths_prefetch_related(self):
        """Test generate_paths function with prefetch_related."""
        specific_fields = {
            "DeepModelLevel1": ["name", "comprehensive_models"],
            "ComprehensiveModel": ["char_field", "int_field"]
        }
        self._test_optimization(
            DeepModelLevel1,
            fields=['name', 'comprehensive_models__char_field', 'comprehensive_models__int_field'],  # Original fields for comparison
            expected_max_queries=2,  # Main query + prefetch query
            description="Generate Paths Prefetch-Related",
            generate_paths_mode=True,
            depth=2,
            specific_fields=specific_fields
        )

    def test_use_only_parameter(self):
        """Test the use_only parameter of the optimizer."""
        fields = [
            'name',
            'category__name'
        ]
        
        # Create optimizers with different use_only settings
        optimizer_with_only = DjangoQueryOptimizer(
            get_model_name_func=self.get_model_name,
            use_only=True
        )
        
        optimizer_without_only = DjangoQueryOptimizer(
            get_model_name_func=self.get_model_name,
            use_only=False
        )
        
        # Test the optimizer with use_only=True
        reset_queries()
        with CaptureQueriesContext(connection) as context:
            optimized_with_only = optimizer_with_only.optimize(
                Product.objects.all(), 
                fields=fields
            )
            objects = list(optimized_with_only)
            count_with_only = len(objects)
            queries_with_only = len(context.captured_queries)
        
        # Test the optimizer with use_only=False
        reset_queries()
        with CaptureQueriesContext(connection) as context:
            optimized_without_only = optimizer_without_only.optimize(
                Product.objects.all(), 
                fields=fields
            )
            objects = list(optimized_without_only)
            count_without_only = len(objects)
            queries_without_only = len(context.captured_queries)
        
        # Both should work but might generate different queries
        print(f"\nUse Only Parameter Test:")
        print(f"Row count with use_only=True: {count_with_only}")
        print(f"Row count with use_only=False: {count_without_only}")
        print(f"With use_only=True: {queries_with_only} queries")
        print(f"With use_only=False: {queries_without_only} queries")
        
        # Both should return the same results
        with_only_ids = list(optimized_with_only.values_list('id', flat=True))
        without_only_ids = list(optimized_without_only.values_list('id', flat=True))
        self.assertEqual(with_only_ids, without_only_ids)
        self.assertEqual(count_with_only, count_without_only)


class ForcePrefetchTests(TestCase):
    """Tests for force_prefetch in ModelConfig."""

    @classmethod
    def setUpTestData(cls):
        """Create test data for prefetch tests."""
        from datetime import date

        # Create rate plans with daily rates
        for i in range(3):
            rate_plan = RatePlan.objects.create(name=f"Rate Plan {i}")
            for j in range(5):
                DailyRate.objects.create(
                    rate_plan=rate_plan,
                    date=date(2024, 1, j + 1),
                    price=100 + i * 10 + j
                )

    def test_force_prefetch_reduces_queries(self):
        """Test that force_prefetch in ModelConfig reduces queries when accessing related fields."""
        from statezero.core.config import ModelConfig, Registry

        # First, test without force_prefetch (N+1 problem)
        reset_queries()
        with CaptureQueriesContext(connection) as context:
            daily_rates = list(DailyRate.objects.all())
            for dr in daily_rates:
                _ = str(dr)  # This accesses self.rate_plan.name
            unoptimized_query_count = len(context.captured_queries)

        # Now test with force_prefetch via the optimizer directly
        reset_queries()
        with CaptureQueriesContext(connection) as context:
            optimizer = DjangoQueryOptimizer(
                get_model_name_func=lambda m: m.__name__,
                use_only=True
            )

            # Simulate what force_prefetch would add
            optimized_qs = optimizer.optimize(
                DailyRate.objects.all(),
                fields=['date', 'price', 'rate_plan__name']  # rate_plan__name triggers select_related
            )
            daily_rates = list(optimized_qs)
            for dr in daily_rates:
                _ = str(dr)  # This should NOT trigger additional queries
            optimized_query_count = len(context.captured_queries)

        print(f"\nforce_prefetch Test Results:")
        print(f"Without optimization: {unoptimized_query_count} queries")
        print(f"With optimization: {optimized_query_count} queries")
        print(f"Query reduction: {unoptimized_query_count - optimized_query_count} queries")

        # The optimized version should have far fewer queries
        self.assertLess(
            optimized_query_count, unoptimized_query_count,
            f"Optimized ({optimized_query_count}) should use fewer queries than unoptimized ({unoptimized_query_count})"
        )
        self.assertEqual(
            optimized_query_count, 1,
            "With force_prefetch fields, should only need 1 query (with select_related)"
        )

    def test_without_prefetch_causes_n_plus_one(self):
        """Test that without prefetching, accessing related fields in __str__ causes N+1."""
        # Verify that DailyRate.__str__ actually accesses rate_plan.name
        rate_plan = RatePlan.objects.first()
        daily_rate = DailyRate.objects.filter(rate_plan=rate_plan).first()
        expected_str = f"{rate_plan.name} - {daily_rate.date}"
        self.assertEqual(str(daily_rate), expected_str)

        # Now test that without prefetching, we get N+1 queries
        reset_queries()
        with CaptureQueriesContext(connection) as context:
            daily_rates = list(DailyRate.objects.all())
            count = len(daily_rates)
            for dr in daily_rates:
                _ = str(dr)
            query_count = len(context.captured_queries)

        # Should be 1 (initial) + N (one per rate_plan access) = N+1 queries
        self.assertGreater(
            query_count, 1,
            f"Without prefetching, should have N+1 queries, got {query_count}"
        )
        print(f"\nN+1 verification: {count} objects caused {query_count} queries (expected ~{count + 1})")