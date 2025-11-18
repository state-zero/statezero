"""
Security tests to ensure users cannot bypass field filtering by providing restricted fields.
This tests that when fields are excluded from the permission-allowed fields:
1. User cannot directly provide those fields in the request
2. Only hooks can add those fields
3. User-provided values for restricted fields are filtered out
"""
import json
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from tests.django_app.models import Product, ProductCategory, Order, OrderItem
from statezero.adaptors.django.config import registry


class TestHookFieldSecurity(APITestCase):
    """Test that users cannot bypass field filtering without hooks"""

    def setUp(self):
        # Create and log in a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        self.category = ProductCategory.objects.create(name="Test Category")

    def test_create_cannot_bypass_field_filtering(self):
        """Test that user cannot provide restricted 'order' field in create without hook"""

        # Create test data
        product = Product.objects.create(
            name="Test Product",
            description="A test product",
            price="99.99",
            category=self.category
        )
        order = Order.objects.create(
            order_number="CREATE001",
            customer_name="Create Customer",
            customer_email="create@example.com",
            total="99.99"
        )

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_fields = model_config.fields

        # Set fields to exclude 'order' - WITHOUT any hook
        model_config.fields = {'product', 'quantity', 'price'}

        try:
            # Try to create with 'order' field directly in user request (should be filtered out)
            payload = {
                "ast": {
                    "query": {
                        "type": "create",
                        "data": {
                            "product": product.id,
                            "quantity": 2,
                            "price": "99.99",
                            "order": order.id,  # MALICIOUS: User trying to bypass filtering
                        },
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Request should fail because 'order' is required but not allowed
            self.assertIn(response.status_code, [400, 500])  # Should fail validation

        finally:
            model_config.fields = original_fields

    def test_bulk_create_cannot_bypass_field_filtering(self):
        """Test that user cannot provide restricted 'order' field in bulk_create without hook"""

        # Create test data
        product = Product.objects.create(
            name="Bulk Product",
            description="A bulk product",
            price="49.99",
            category=self.category
        )
        order = Order.objects.create(
            order_number="BULK001",
            customer_name="Bulk Customer",
            customer_email="bulk@example.com",
            total="199.99"
        )

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_fields = model_config.fields

        # Set fields to exclude 'order' - WITHOUT any hook
        model_config.fields = {'product', 'quantity', 'price'}

        try:
            # Try to bulk_create with 'order' field directly in user request
            payload = {
                "ast": {
                    "query": {
                        "type": "bulk_create",
                        "data": [
                            {
                                "product": product.id,
                                "quantity": 1,
                                "price": "49.99",
                                "order": order.id,  # MALICIOUS: User trying to bypass filtering
                            },
                            {
                                "product": product.id,
                                "quantity": 2,
                                "price": "99.99",
                                "order": order.id,  # MALICIOUS: User trying to bypass filtering
                            },
                        ],
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Request should fail because 'order' is required but not allowed
            self.assertIn(response.status_code, [400, 500])  # Should fail validation

        finally:
            model_config.fields = original_fields

    def test_update_instance_cannot_bypass_field_filtering(self):
        """Test that user cannot provide restricted field in update without hook"""

        # Create test data
        product1 = Product.objects.create(
            name="Product 1",
            description="First product",
            price="99.99",
            category=self.category
        )
        order1 = Order.objects.create(
            order_number="UPDATE001",
            customer_name="Update Customer",
            customer_email="update@example.com",
            total="99.99"
        )
        order2 = Order.objects.create(
            order_number="UPDATE002",
            customer_name="Another Customer",
            customer_email="another@example.com",
            total="199.99"
        )

        # Create an item with order1
        item = OrderItem.objects.create(
            order=order1,
            product=product1,
            quantity=1,
            price="99.99"
        )

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_fields = model_config.fields

        # Set fields to exclude 'order' - WITHOUT any hook
        model_config.fields = {'product', 'quantity', 'price'}

        try:
            # Try to update with 'order' field directly in user request (should be filtered out)
            payload = {
                "ast": {
                    "query": {
                        "type": "update_instance",
                        "filter": {"type": "filter", "conditions": {"id": item.id}},
                        "data": {
                            "quantity": 5,
                            "order": order2.id,  # MALICIOUS: User trying to change order
                        },
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Request should succeed but 'order' should NOT be changed
            self.assertEqual(response.status_code, 200)

            # Verify the update worked for allowed field
            item.refresh_from_db()
            self.assertEqual(item.quantity, 5)

            # CRITICAL: Verify 'order' was NOT changed (user input was filtered)
            self.assertEqual(item.order.id, order1.id)  # Should still be order1, not order2

        finally:
            model_config.fields = original_fields

    def test_update_cannot_bypass_field_filtering(self):
        """Test that user cannot provide restricted field in bulk update without hook"""

        # Create test data
        product = Product.objects.create(
            name="Product 1",
            description="First product",
            price="99.99",
            category=self.category
        )
        order1 = Order.objects.create(
            order_number="UPDATE001",
            customer_name="Update Customer",
            customer_email="update@example.com",
            total="99.99"
        )
        order2 = Order.objects.create(
            order_number="UPDATE002",
            customer_name="Another Customer",
            customer_email="another@example.com",
            total="199.99"
        )

        # Create items with order1
        item1 = OrderItem.objects.create(
            order=order1,
            product=product,
            quantity=1,
            price="99.99"
        )
        item2 = OrderItem.objects.create(
            order=order1,
            product=product,
            quantity=2,
            price="99.99"
        )

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_fields = model_config.fields

        # Set fields to exclude 'order' - WITHOUT any hook
        model_config.fields = {'product', 'quantity', 'price'}

        try:
            # Try to bulk update with 'order' field directly in user request
            payload = {
                "ast": {
                    "query": {
                        "type": "update",
                        "filter": {"type": "filter", "conditions": {"order": order1.id}},
                        "data": {
                            "quantity": 10,
                            "order": order2.id,  # MALICIOUS: User trying to change order
                        },
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Request should succeed but 'order' should NOT be changed
            self.assertEqual(response.status_code, 200)

            # Verify the updates worked for allowed field
            item1.refresh_from_db()
            item2.refresh_from_db()
            self.assertEqual(item1.quantity, 10)
            self.assertEqual(item2.quantity, 10)

            # CRITICAL: Verify 'order' was NOT changed (user input was filtered)
            self.assertEqual(item1.order.id, order1.id)
            self.assertEqual(item2.order.id, order1.id)

        finally:
            model_config.fields = original_fields

    def test_get_or_create_cannot_bypass_field_filtering(self):
        """Test that user cannot provide restricted 'order' field in get_or_create without hook"""

        # Create test data
        product = Product.objects.create(
            name="GOC Product",
            description="Get or create product",
            price="79.99",
            category=self.category
        )
        order = Order.objects.create(
            order_number="GOC001",
            customer_name="GOC Customer",
            customer_email="goc@example.com",
            total="79.99"
        )

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_fields = model_config.fields

        # Set fields to exclude 'order' - WITHOUT any hook
        model_config.fields = {'product', 'quantity', 'price'}

        try:
            # Try to get_or_create with 'order' field directly in user request
            payload = {
                "ast": {
                    "query": {
                        "type": "get_or_create",
                        "lookup": {"product": product.id, "quantity": 2},
                        "defaults": {
                            "price": "79.99",
                            "order": order.id,  # MALICIOUS: User trying to bypass filtering
                        },
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Request should fail because 'order' is required but not allowed
            self.assertIn(response.status_code, [400, 500])  # Should fail validation

        finally:
            model_config.fields = original_fields

    def test_update_or_create_cannot_bypass_field_filtering_on_create(self):
        """Test that user cannot provide restricted 'order' field in update_or_create (create path) without hook"""

        # Create test data
        product = Product.objects.create(
            name="UOC Product",
            description="Update or create product",
            price="89.99",
            category=self.category
        )
        order = Order.objects.create(
            order_number="UOC001",
            customer_name="UOC Customer",
            customer_email="uoc@example.com",
            total="89.99"
        )

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_fields = model_config.fields

        # Set fields to exclude 'order' - WITHOUT any hook
        model_config.fields = {'product', 'quantity', 'price'}

        try:
            # Try to update_or_create (will create) with 'order' field directly in user request
            payload = {
                "ast": {
                    "query": {
                        "type": "update_or_create",
                        "lookup": {"product": product.id},
                        "defaults": {
                            "quantity": 1,
                            "price": "89.99",
                            "order": order.id,  # MALICIOUS: User trying to bypass filtering
                        },
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Request should fail because 'order' is required but not allowed
            self.assertIn(response.status_code, [400, 500])  # Should fail validation

        finally:
            model_config.fields = original_fields

    def test_update_or_create_cannot_bypass_field_filtering_on_update(self):
        """Test that user cannot provide restricted 'order' field in update_or_create (update path) without hook"""

        # Create test data
        product = Product.objects.create(
            name="UOC Product",
            description="Update or create product",
            price="89.99",
            category=self.category
        )
        order1 = Order.objects.create(
            order_number="UOC001",
            customer_name="UOC Customer",
            customer_email="uoc@example.com",
            total="89.99"
        )
        order2 = Order.objects.create(
            order_number="UOC002",
            customer_name="Another Customer",
            customer_email="another@example.com",
            total="199.99"
        )

        # Create an existing item
        item = OrderItem.objects.create(
            order=order1,
            product=product,
            quantity=1,
            price="89.99"
        )

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_fields = model_config.fields

        # Set fields to exclude 'order' - WITHOUT any hook
        model_config.fields = {'product', 'quantity', 'price'}

        try:
            # Try to update_or_create (will update) with 'order' field directly in user request
            payload = {
                "ast": {
                    "query": {
                        "type": "update_or_create",
                        "lookup": {"product": product.id},
                        "defaults": {
                            "quantity": 5,
                            "price": "89.99",
                            "order": order2.id,  # MALICIOUS: User trying to change order
                        },
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Request should succeed but 'order' should NOT be changed
            self.assertEqual(response.status_code, 200)

            # Verify the update worked for allowed field
            item.refresh_from_db()
            self.assertEqual(item.quantity, 5)

            # CRITICAL: Verify 'order' was NOT changed (user input was filtered)
            self.assertEqual(item.order.id, order1.id)  # Should still be order1, not order2

        finally:
            model_config.fields = original_fields
