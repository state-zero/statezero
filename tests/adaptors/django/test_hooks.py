import json
import time
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from tests.django_app.models import Order, Product, ProductCategory


class HookApplicationTests(APITestCase):
    def setUp(self):
        # Create and log in a test user
        self.user = User.objects.create_user(
            username="testhookuser", 
            password="password",
            email="testhookuser@example.com"
        )
        self.client.login(username="testhookuser", password="password")
        
        # Create a product category
        self.category = ProductCategory.objects.create(name="Test Category")

    def _generate_unique_id(self):
        """Generate a short unique ID (under 20 chars) for order numbers"""
        # Use millisecond timestamp in hexadecimal for compactness
        timestamp = int(time.time() * 1000)
        hex_time = hex(timestamp)[2:]  # Remove '0x' prefix
        return f"ORD-{hex_time[-8:]}"  # Take last 8 hex chars to keep it short
    
    def test_set_created_by_hook_with_authenticated_user(self):
        """Test that the set_created_by hook correctly sets the created_by field to the authenticated user."""
        
        # Create a product using the API
        payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "Test Product",
                        "description": "A product to test hooks",
                        "price": "29.99",
                        "category": self.category.id,
                        # Intentionally omit created_by to test the hook
                    },
                }
            }
        }
        
        url = reverse("statezero:model_view", args=["django_app.Product"])
        response = self.client.post(url, data=payload, format="json")
        
        # Verify the request was successful
        self.assertEqual(response.status_code, 200)
        
        # Get the ID of the created product
        created_product = response.data.get("data", {})
        product_id = created_product.get("id")
        self.assertIsNotNone(product_id)
        
        # Retrieve the product from the database
        product = Product.objects.get(id=product_id)
        
        # Verify that created_by was set to the authenticated user's username
        self.assertEqual(product.created_by, "testhookuser")
        
    def test_set_created_by_hook_with_unauthenticated_user(self):
        """Test that the set_created_by hook sets created_by to 'system' when user is not authenticated."""
        
        # Logout the user
        self.client.logout()
        
        # Create a product using the API
        payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "Unauthenticated Product",
                        "description": "Testing hooks without auth",
                        "price": "19.99",
                        "category": self.category.id,
                        # Intentionally omit created_by to test the hook
                    },
                }
            }
        }
        
        url = reverse("statezero:model_view", args=["django_app.Product"])
        response = self.client.post(url, data=payload, format="json")
        
        # Verify the request was successful
        self.assertEqual(response.status_code, 200)
        
        # Get the ID of the created product
        created_product = response.data.get("data", {})
        product_id = created_product.get("id")
        self.assertIsNotNone(product_id)
        
        # Retrieve the product from the database
        product = Product.objects.get(id=product_id)
        
        # Verify that created_by was set to 'system'
        self.assertEqual(product.created_by, "system")
        
    def test_order_hooks_application(self):
        """Test that both pre and post hooks for orders are correctly applied."""
        
        # Log back in to ensure user is authenticated
        self.client.login(username="testhookuser", password="password")
        
        # Create an order with a mixed-case email
        # Using "DUMMY" as the order number to test the post-hook replacement
        payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "customer_name": "Test Customer",
                        "customer_email": "TEST.CUSTOMER@EXAMPLE.COM",  # Email to be normalized
                        "order_number": "DUMMY",  # Should be replaced by post-hook
                        "status": "pending",  # Using valid status value
                        "total": "99.99",
                    },
                }
            }
        }
        
        url = reverse("statezero:model_view", args=["django_app.Order"])
        response = self.client.post(url, data=payload, format="json")
        
        # Verify the request was successful
        self.assertEqual(response.status_code, 200)
        
        # Get the ID of the created order
        created_order = response.data.get("data", {})
        order_id = created_order.get("id")
        self.assertIsNotNone(order_id)
        
        # Retrieve the order from the database
        order = Order.objects.get(id=order_id)
        
        # Verify that pre-hook normalized the email
        self.assertEqual(order.customer_email, "test.customer@example.com")
        
        # Verify that post-hook generated a proper order number
        self.assertNotEqual(order.order_number, "DUMMY")
        self.assertTrue(order.order_number.startswith("ORD-"))
        
    def test_hooks_on_update_operations(self):
        """Test that hooks are properly applied to update operations."""
        
        # First create an order directly in the database
        initial_order_number = self._generate_unique_id()
        
        order = Order.objects.create(
            customer_name="Update Test",
            customer_email="UPDATE.TEST@EXAMPLE.COM",
            order_number=initial_order_number,  # Valid order number, should be preserved
            status="pending",
            total="49.99"
        )
        
        # Now update the order via the API
        payload = {
            "ast": {
                "query": {
                    "type": "update_instance",
                    "filter": {"type": "filter", "conditions": {"id": order.id}},
                    "data": {
                        "customer_name": "Updated Name",
                        "customer_email": "UPDATED.EMAIL@EXAMPLE.COM",
                        # Don't include order_number in the update
                    },
                }
            }
        }
        
        url = reverse("statezero:model_view", args=["django_app.Order"])
        response = self.client.post(url, data=payload, format="json")
        
        # Verify the request was successful
        self.assertEqual(response.status_code, 200)
        
        # Refresh the order from the database
        order.refresh_from_db()
        
        # Verify pre-hook normalized the updated email
        self.assertEqual(order.customer_email, "updated.email@example.com")
        
        # Now test with a "DUMMY" order number to see if post-hook replaces it
        update_with_dummy_payload = {
            "ast": {
                "query": {
                    "type": "update_instance",
                    "filter": {"type": "filter", "conditions": {"id": order.id}},
                    "data": {
                        "order_number": "DUMMY",  # Should be replaced by post-hook
                    },
                }
            }
        }
        
        dummy_update_response = self.client.post(url, data=update_with_dummy_payload, format="json")
        self.assertEqual(dummy_update_response.status_code, 200)
        
        # Refresh the order from the database
        order.refresh_from_db()
        
        # Verify post-hook replaced "DUMMY" with a generated order number
        self.assertNotEqual(order.order_number, "DUMMY")
        self.assertTrue(order.order_number.startswith("ORD-"))
        
    def test_hooks_on_update_or_create(self):
        """Test that hooks are properly applied to update_or_create operations."""
        
        # Create a unique identifier for the test
        unique_prefix = f"TestHook{int(time.time() % 10000)}"
        initial_order_number = self._generate_unique_id()
        
        # Use update_or_create to create a new order (should apply both hooks)
        payload = {
            "ast": {
                "query": {
                    "type": "update_or_create",
                    "lookup": {"customer_name": f"{unique_prefix}"},
                    "defaults": {
                        "customer_email": "UOC.TEST@EXAMPLE.COM",
                        "status": "pending",
                        "total": "29.99",
                        "order_number": initial_order_number,  # Include valid order number
                    },
                }
            }
        }
        
        url = reverse("statezero:model_view", args=["django_app.Order"])
        response = self.client.post(url, data=payload, format="json")
        
        # Verify the request was successful
        self.assertEqual(response.status_code, 200)
        
        # Get the ID of the created order
        created_data = response.data.get("data", {})
        order_id = created_data.get("id")
        self.assertIsNotNone(order_id)
        
        # Verify metadata indicates creation
        metadata = response.data.get("metadata", {})
        self.assertTrue(metadata.get("created", False))
        
        # Retrieve the order from the database
        order = Order.objects.get(id=order_id)
        
        # Verify pre-hook normalized the email
        self.assertEqual(order.customer_email, "uoc.test@example.com")
        
        # Verify post-hook replaced "DUMMY" with a generated order number
        self.assertNotEqual(order.order_number, "DUMMY")
        self.assertTrue(order.order_number.startswith("ORD-"))
        
        # Get the current order number for later comparison
        current_order_number = order.order_number + "X"  # Add a suffix to avoid matching
        
        # Now use update_or_create to update the existing order
        # Include both order_number and total in defaults
        update_payload = {
            "ast": {
                "query": {
                    "type": "update_or_create",
                    "lookup": {"customer_name": f"{unique_prefix}"},
                    "defaults": {
                        "customer_email": "UPDATED.UOC@EXAMPLE.COM",
                        "status": "processing",
                        "order_number": current_order_number,  # Include existing order number
                        "total": "39.99",  # Include total
                    },
                }
            }
        }
        
        update_response = self.client.post(url, data=update_payload, format="json")
        
        # Verify the request was successful
        self.assertEqual(update_response.status_code, 200)
        
        # Verify metadata indicates update (not creation)
        update_metadata = update_response.data.get("metadata", {})
        self.assertFalse(update_metadata.get("created", True))
        
        # Refresh the order from the database
        order.refresh_from_db()
        
        # Verify status was updated
        self.assertEqual(order.status, "processing")
        
        # Verify pre-hook normalized the updated email
        self.assertEqual(order.customer_email, "updated.uoc@example.com")
        
        # Test with a DUMMY order number in update_or_create
        dummy_update_payload = {
            "ast": {
                "query": {
                    "type": "update_or_create",
                    "lookup": {"customer_name": f"{unique_prefix}"},
                    "defaults": {
                        "order_number": "DUMMY2",  # Should be replaced by post-hook
                        "total": "49.99",  # Still include total
                    },
                }
            }
        }
        
        dummy_update_response = self.client.post(url, data=dummy_update_payload, format="json")
        self.assertEqual(dummy_update_response.status_code, 200)
        
        # Refresh the order from the database
        order.refresh_from_db()
        
        # Verify post-hook replaced "DUMMY" with a generated order number
        self.assertNotEqual(order.order_number, "DUMMY")
        self.assertTrue(order.order_number.startswith("ORD-"))