import time
from django.test import TestCase
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests.django_app.models import (
    Product, ProductCategory, Order, OrderItem,
    DeepModelLevel1, DeepModelLevel2, DeepModelLevel3,
    ComprehensiveModel
)

# Import the query optimizer function
from ormbridge.adaptors.django.query_optimizer import optimize_query


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
    
    def _test_optimization(self, model, fields, expected_max_queries, description):
        """
        Shared test logic for all optimization tests.
        
        Tests:
        1. Query count is reduced
        2. Performance is improved 
        3. Results are identical
        """
        # Get baseline results for comparison
        baseline_queryset = model.objects.all()
        baseline_ids = list(baseline_queryset.values_list('id', flat=True))
        
        # Test unoptimized query
        reset_queries()
        start_time = time.time()
        with CaptureQueriesContext(connection) as context:
            # Get all objects
            objects = list(baseline_queryset)
            
            # Access fields to trigger lazy loading
            for obj in objects:
                self._access_fields(obj, fields)
                
            unoptimized_query_count = len(context.captured_queries)
        unoptimized_time = time.time() - start_time
        
        # Test optimized query
        reset_queries()
        start_time = time.time()
        with CaptureQueriesContext(connection) as context:
            # Optimize the query
            optimized_qs = optimize_query(model.objects.all(), fields)
            objects = list(optimized_qs)
            
            # Access the same fields
            for obj in objects:
                self._access_fields(obj, fields)
                
            optimized_query_count = len(context.captured_queries)
        optimized_time = time.time() - start_time
        
        # Get optimized query results for comparison
        optimized_ids = list(optimized_qs.values_list('id', flat=True))
        
        # Print performance metrics
        print(f"\n{description} Results:")
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
        
        # 3. Results should be identical
        self.assertEqual(
            optimized_ids, baseline_ids,
            "Optimized query returned different results than baseline"
        )
        
        # 4. Time should be better or at least not significantly worse
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
    
    def test_filtering_with_optimization(self):
        """Test that optimization works with filtering."""
        fields = [
            'name',
            'price',
            'category__name'
        ]
        
        # Create a filtered queryset
        filtered_qs = Product.objects.filter(price__gt=20)
        filtered_ids = list(filtered_qs.values_list('id', flat=True))
        
        # Test unoptimized
        reset_queries()
        start_time = time.time()
        with CaptureQueriesContext(connection) as context:
            objects = list(filtered_qs)
            for obj in objects:
                _ = obj.category.name
            unoptimized_query_count = len(context.captured_queries)
        unoptimized_time = time.time() - start_time
        
        # Test optimized
        reset_queries()
        start_time = time.time()
        with CaptureQueriesContext(connection) as context:
            optimized_qs = optimize_query(filtered_qs, fields)
            objects = list(optimized_qs)
            for obj in objects:
                _ = obj.category.name
            optimized_query_count = len(context.captured_queries)
        optimized_time = time.time() - start_time
        
        # Get results
        optimized_ids = list(optimized_qs.values_list('id', flat=True))
        
        # Print metrics
        print(f"\nFiltering with Optimization Results:")
        print(f"Unoptimized: {unoptimized_query_count} queries, {unoptimized_time:.4f}s")
        print(f"Optimized: {optimized_query_count} queries, {optimized_time:.4f}s")
        
        # Assertions
        self.assertLess(optimized_query_count, unoptimized_query_count)
        self.assertEqual(optimized_ids, filtered_ids)