"""
Test that pre-hooks can add fields that aren't in the permission-allowed fields.
This tests the behavior where:
1. User input is filtered to only allowed fields
2. Pre-hooks can add any DB field (not in allowed fields)
3. Hook-added fields persist to the database across all write operations
"""
import json
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from tests.django_app.models import Product, ProductCategory, Order, OrderItem
from statezero.adaptors.django.config import registry


class TestHookFieldPersistence(APITestCase):
    """Test that pre-hooks can add DB fields not in the allowed fields_map across all write operations"""

    def setUp(self):
        # Create and log in a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        self.category = ProductCategory.objects.create(name="Test Category")

    def test_hook_fields_persist_with_create(self):
        """Test that hook-added ForeignKey fields persist with create operation"""

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

        # Define a hook that adds the 'order' ForeignKey field
        def add_order_hook(data, request=None):
            data = data.copy()
            data['order'] = order.id
            return data

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_hooks = model_config.pre_hooks
        original_fields = model_config.fields

        # Set fields to exclude 'order' - simulating the Address model scenario
        model_config.fields = {'product', 'quantity', 'price'}
        model_config.pre_hooks = [add_order_hook]

        try:
            # Create via API
            payload = {
                "ast": {
                    "query": {
                        "type": "create",
                        "data": {
                            "product": product.id,
                            "quantity": 2,
                            "price": "99.99",
                        },
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Verify the request was successful
            self.assertEqual(response.status_code, 200)

            # Get the created instance ID
            # Response structure: {'data': {'data': [id], 'included': {...}}}
            data_wrapper = response.data.get("data", {})
            instance_ids = data_wrapper.get("data", [])
            self.assertEqual(len(instance_ids), 1)
            instance_id = instance_ids[0]
            self.assertIsNotNone(instance_id)

            # Verify it persisted to the database with the hook-added 'order' field
            saved_instance = OrderItem.objects.get(id=instance_id)
            self.assertIsNotNone(saved_instance.order)
            self.assertEqual(saved_instance.order.id, order.id)
            self.assertEqual(saved_instance.quantity, 2)

        finally:
            model_config.pre_hooks = original_hooks
            model_config.fields = original_fields

    def test_hook_fields_persist_with_bulk_create(self):
        """Test that hook-added ForeignKey fields persist with bulk_create operation"""

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

        # Define a hook that adds the 'order' ForeignKey field
        def add_order_hook(data, request=None):
            data = data.copy()
            data['order'] = order.id
            return data

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_hooks = model_config.pre_hooks
        original_fields = model_config.fields

        # Set fields to exclude 'order'
        model_config.fields = {'product', 'quantity', 'price'}
        model_config.pre_hooks = [add_order_hook]

        try:
            # Create via API using bulk_create
            payload = {
                "ast": {
                    "query": {
                        "type": "bulk_create",
                        "data": [
                            {"product": product.id, "quantity": 1, "price": "49.99"},
                            {"product": product.id, "quantity": 2, "price": "99.99"},
                            {"product": product.id, "quantity": 3, "price": "149.99"},
                        ],
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Verify the request was successful
            self.assertEqual(response.status_code, 200)

            # Get the created instance IDs from the response
            # Response structure: {'data': {'data': [id1, id2, id3], 'included': {...}}}
            data_wrapper = response.data.get("data", {})
            instance_ids = data_wrapper.get("data", [])
            self.assertEqual(len(instance_ids), 3)

            # Verify all persisted to the database with the hook-added 'order' field
            for instance_id in instance_ids:
                saved_instance = OrderItem.objects.get(id=instance_id)
                self.assertIsNotNone(saved_instance.order)
                self.assertEqual(saved_instance.order.id, order.id)

        finally:
            model_config.pre_hooks = original_hooks
            model_config.fields = original_fields

    def test_hook_fields_persist_with_update_instance(self):
        """Test that hook-added fields work with update_instance operation"""

        # Create test data
        product1 = Product.objects.create(
            name="Product 1",
            description="First product",
            price="99.99",
            category=self.category
        )
        product2 = Product.objects.create(
            name="Product 2",
            description="Second product",
            price="199.99",
            category=self.category
        )
        order = Order.objects.create(
            order_number="UPDATE001",
            customer_name="Update Customer",
            customer_email="update@example.com",
            total="99.99"
        )

        # Create an item with product1
        item = OrderItem.objects.create(
            order=order,
            product=product1,
            quantity=1,
            price="99.99"
        )

        # Define a hook that modifies a field on update
        def modify_price_hook(data, request=None):
            data = data.copy()
            # Set price to a specific value to prove hook ran
            data['price'] = '999.99'
            return data

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_hooks = model_config.pre_hooks
        original_fields = model_config.fields

        # Set fields to only allow 'quantity'
        model_config.fields = {'quantity', 'price'}
        model_config.pre_hooks = [modify_price_hook]

        try:
            # Update via API
            payload = {
                "ast": {
                    "query": {
                        "type": "update_instance",
                        "filter": {"type": "filter", "conditions": {"id": item.id}},
                        "data": {
                            "quantity": 5,
                        },
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Verify the request was successful
            self.assertEqual(response.status_code, 200)

            # Verify the update worked
            item.refresh_from_db()
            self.assertEqual(item.quantity, 5)
            self.assertEqual(str(item.price), '999.99')  # Hook modified this

        finally:
            model_config.pre_hooks = original_hooks
            model_config.fields = original_fields

    def test_hook_fields_persist_with_update(self):
        """Test that hook-added fields work with bulk update operation"""

        # Create test data
        product = Product.objects.create(
            name="Product 1",
            description="First product",
            price="99.99",
            category=self.category
        )
        order = Order.objects.create(
            order_number="UPDATE001",
            customer_name="Update Customer",
            customer_email="update@example.com",
            total="99.99"
        )

        # Create items
        item1 = OrderItem.objects.create(
            order=order,
            product=product,
            quantity=1,
            price="99.99"
        )
        item2 = OrderItem.objects.create(
            order=order,
            product=product,
            quantity=2,
            price="99.99"
        )

        # Define a hook that modifies a field on update
        def modify_price_hook(data, request=None):
            data = data.copy()
            # Set price to a specific value to prove hook ran
            data['price'] = '888.88'
            return data

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_hooks = model_config.pre_hooks
        original_fields = model_config.fields

        # Set fields to only allow 'quantity'
        model_config.fields = {'quantity', 'price'}
        model_config.pre_hooks = [modify_price_hook]

        try:
            # Update via API (bulk update)
            payload = {
                "ast": {
                    "query": {
                        "type": "update",
                        "filter": {"type": "filter", "conditions": {"order": order.id}},
                        "data": {
                            "quantity": 10,
                        },
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Verify the request was successful
            self.assertEqual(response.status_code, 200)

            # Verify the updates worked
            item1.refresh_from_db()
            item2.refresh_from_db()
            self.assertEqual(item1.quantity, 10)
            self.assertEqual(item2.quantity, 10)
            self.assertEqual(str(item1.price), '888.88')  # Hook modified this
            self.assertEqual(str(item2.price), '888.88')  # Hook modified this

        finally:
            model_config.pre_hooks = original_hooks
            model_config.fields = original_fields

    def test_hook_fields_persist_with_get_or_create(self):
        """Test that hook-added fields work with get_or_create operation"""

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

        # Define a hook that adds the 'order' field
        def add_order_hook(data, request=None):
            data = data.copy()
            data['order'] = order.id
            return data

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_hooks = model_config.pre_hooks
        original_fields = model_config.fields

        model_config.fields = {'product', 'quantity', 'price'}
        model_config.pre_hooks = [add_order_hook]

        try:
            # First call - should create
            payload = {
                "ast": {
                    "query": {
                        "type": "get_or_create",
                        "lookup": {"product": product.id, "quantity": 2},
                        "defaults": {"price": "79.99"},
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Verify the request was successful
            self.assertEqual(response.status_code, 200)

            # Get the instance ID
            data_wrapper = response.data.get("data", {})
            instance_ids = data_wrapper.get("data", [])
            self.assertEqual(len(instance_ids), 1)
            instance_id = instance_ids[0]
            self.assertIsNotNone(instance_id)

            # Verify it was created with the hook-added field
            saved_instance = OrderItem.objects.get(id=instance_id)
            self.assertIsNotNone(saved_instance.order)
            self.assertEqual(saved_instance.order.id, order.id)
            self.assertEqual(saved_instance.quantity, 2)

            # Second call with same lookup - should get existing (not create)
            response2 = self.client.post(url, data=payload, format="json")
            self.assertEqual(response2.status_code, 200)

            # Should return the same instance
            data_wrapper2 = response2.data.get("data", {})
            instance_ids2 = data_wrapper2.get("data", [])
            instance_id2 = instance_ids2[0]
            self.assertEqual(instance_id2, instance_id)

            # Should still only have one OrderItem in DB
            self.assertEqual(OrderItem.objects.filter(product=product, quantity=2).count(), 1)

        finally:
            model_config.pre_hooks = original_hooks
            model_config.fields = original_fields

    def test_hook_fields_persist_with_update_or_create(self):
        """Test that hook-added fields work with update_or_create operation"""

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

        # Define a hook that adds the 'order' field
        def add_order_hook(data, request=None):
            data = data.copy()
            data['order'] = order.id
            return data

        # Get model config and temporarily modify it
        model_config = registry.get_config(OrderItem)
        original_hooks = model_config.pre_hooks
        original_fields = model_config.fields

        model_config.fields = {'product', 'quantity', 'price'}
        model_config.pre_hooks = [add_order_hook]

        try:
            # First call - should create
            payload = {
                "ast": {
                    "query": {
                        "type": "update_or_create",
                        "lookup": {"product": product.id},
                        "defaults": {"quantity": 1, "price": "89.99"},
                    }
                }
            }

            url = reverse("statezero:model_view", args=["django_app.OrderItem"])
            response = self.client.post(url, data=payload, format="json")

            # Verify the request was successful
            self.assertEqual(response.status_code, 200)

            # Get the instance ID
            data_wrapper = response.data.get("data", {})
            instance_ids = data_wrapper.get("data", [])
            self.assertEqual(len(instance_ids), 1)
            instance_id = instance_ids[0]
            self.assertIsNotNone(instance_id)

            # Verify it was created with the hook-added field
            saved_instance = OrderItem.objects.get(id=instance_id)
            self.assertIsNotNone(saved_instance.order)
            self.assertEqual(saved_instance.order.id, order.id)
            self.assertEqual(saved_instance.quantity, 1)

            # Second call with same lookup - should update
            payload2 = {
                "ast": {
                    "query": {
                        "type": "update_or_create",
                        "lookup": {"product": product.id},
                        "defaults": {"quantity": 3, "price": "89.99"},
                    }
                }
            }

            response2 = self.client.post(url, data=payload2, format="json")
            self.assertEqual(response2.status_code, 200)

            # Should return the same instance (updated)
            data_wrapper2 = response2.data.get("data", {})
            instance_ids2 = data_wrapper2.get("data", [])
            instance_id2 = instance_ids2[0]
            self.assertEqual(instance_id2, instance_id)

            # Verify the update worked
            saved_instance.refresh_from_db()
            self.assertEqual(saved_instance.quantity, 3)

        finally:
            model_config.pre_hooks = original_hooks
            model_config.fields = original_fields
