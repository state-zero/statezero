from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase
from statezero.adaptors.django.models import ModelViewSubscription
from tests.django_app.models import DummyModel, DummyRelatedModel
from unittest.mock import patch

User = get_user_model()

class ModelViewSubscriptionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.user2 = User.objects.create_user(username="testuser2", password="password")
        self.model_name = "django_app.DummyModel"
        # Match the frontend structure exactly
        self.ast_query = {
            "query": {
                "type": "list",  # Changed from "read" to "list"
                "filter": {"type": "filter", "conditions": {"value__gte": 10}},
                "search": None,  # Added missing field
                "aggregations": []  # Added missing field
            },
            "serializerOptions": {}  # Added missing wrapper
        }
        # Update response_data to match the actual nested structure
        self.response_data = {
            "data": {
                "data": [1], 
                "included": {"django_app.dummymodel": {1: {"id": 1, "name": "test"}}},
                "model_name": "django_app.DummyModel"
            },
            "metadata": {"read": True, "response_type": "queryset"}
        }
    
    def test_initialize_legacy_method(self):
        """Test the legacy initialize method still works."""
        live_view = ModelViewSubscription.initialize(
            user=self.user,
            model_name=self.model_name,
            ast_query=self.ast_query,
            response_data=self.response_data
        )
        
        self.assertEqual(live_view.user, self.user)
        self.assertEqual(live_view.model_name, self.model_name)
        self.assertEqual(live_view.ast_query, self.ast_query)
        self.assertEqual(live_view.cached_response, self.response_data)
        self.assertIsNotNone(live_view.response_hash)
        self.assertIsNotNone(live_view.channel_name)
        self.assertFalse(live_view.has_error)
        self.assertTrue(live_view.is_active)

    def test_update_or_create_subscription_creates_new(self):
        """Test that update_or_create_subscription creates a new subscription when none exists."""
        subscription, created = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=self.ast_query,
            response_data=self.response_data
        )
        
        self.assertTrue(created)
        self.assertEqual(subscription.user, self.user)
        self.assertEqual(subscription.model_name, self.model_name)
        self.assertEqual(subscription.ast_query, self.ast_query)
        self.assertEqual(subscription.cached_response, self.response_data)
        self.assertIsNotNone(subscription.response_hash)
        self.assertIsNotNone(subscription.channel_name)
        self.assertFalse(subscription.has_error)
        self.assertTrue(subscription.is_active)

    def test_update_or_create_subscription_updates_existing(self):
        """Test that update_or_create_subscription updates an existing subscription."""
        # Create initial subscription
        subscription1, created1 = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=self.ast_query,
            response_data=self.response_data
        )
        self.assertTrue(created1)
        
        original_id = subscription1.id
        original_created_at = subscription1.created_at
        original_hash = subscription1.response_hash
        
        # New response data
        new_response_data = {
            "data": {
                "data": [1, 2], 
                "included": {
                    "django_app.dummymodel": {
                        1: {"id": 1, "name": "test"},
                        2: {"id": 2, "name": "test2"}
                    }
                },
                "model_name": "django_app.DummyModel"
            },
            "metadata": {"read": True, "response_type": "queryset"}
        }
        
        # Update the same subscription
        subscription2, created2 = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=self.ast_query,  # Same query
            response_data=new_response_data
        )
        
        self.assertFalse(created2)  # Should be an update, not create
        self.assertEqual(subscription2.id, original_id)  # Same instance
        self.assertEqual(subscription2.created_at, original_created_at)  # Created at unchanged
        self.assertEqual(subscription2.cached_response, new_response_data)  # Updated data
        self.assertNotEqual(subscription2.response_hash, original_hash)  # New hash
        self.assertTrue(subscription2.is_active)
        self.assertFalse(subscription2.has_error)

    def test_update_or_create_subscription_different_queries_different_subscriptions(self):
        """Test that different queries create different subscriptions for same user/model."""
        # First subscription
        ast_query1 = {
            "query": {
                "type": "list",
                "filter": {"type": "filter", "conditions": {"value__gte": 10}},
                "search": None,
                "aggregations": []
            },
            "serializerOptions": {}
        }
        
        subscription1, created1 = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=ast_query1,
            response_data=self.response_data
        )
        self.assertTrue(created1)
        
        # Second subscription with different query
        ast_query2 = {
            "query": {
                "type": "list",
                "filter": {"type": "filter", "conditions": {"value__lt": 5}},  # Different filter
                "search": None,
                "aggregations": []
            },
            "serializerOptions": {}
        }
        
        subscription2, created2 = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=ast_query2,
            response_data=self.response_data
        )
        self.assertTrue(created2)
        
        # Should be different subscriptions
        self.assertNotEqual(subscription1.id, subscription2.id)
        self.assertNotEqual(subscription1.channel_name, subscription2.channel_name)

    def test_update_or_create_subscription_different_users_same_query(self):
        """Test that different users can have subscriptions for the same query."""
        subscription1, created1 = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=self.ast_query,
            response_data=self.response_data
        )
        self.assertTrue(created1)
        
        subscription2, created2 = ModelViewSubscription.update_or_create_subscription(
            user=self.user2,  # Different user
            model_name=self.model_name,
            ast_query=self.ast_query,  # Same query
            response_data=self.response_data
        )
        self.assertTrue(created2)
        
        # Should be different subscriptions (different users)
        self.assertNotEqual(subscription1.id, subscription2.id)
        self.assertEqual(subscription1.channel_name, subscription2.channel_name)  # Same channel (same query)
        self.assertEqual(subscription1.user, self.user)
        self.assertEqual(subscription2.user, self.user2)

    def test_update_or_create_reactivates_inactive_subscription(self):
        """Test that update_or_create reactivates an inactive subscription."""
        # Create and then deactivate a subscription
        subscription1, created1 = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=self.ast_query,
            response_data=self.response_data
        )
        self.assertTrue(created1)
        
        subscription1.deactivate()
        self.assertFalse(subscription1.is_active)
        
        # Update with new data should reactivate
        new_response_data = {"different": "data"}
        subscription2, created2 = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=self.ast_query,
            response_data=new_response_data
        )
        
        self.assertFalse(created2)  # Should be an update
        self.assertEqual(subscription2.id, subscription1.id)  # Same instance
        self.assertTrue(subscription2.is_active)  # Reactivated
        self.assertEqual(subscription2.cached_response, new_response_data)
        self.assertFalse(subscription2.has_error)

    def test_deactivate_and_reactivate_methods(self):
        """Test the deactivate and reactivate helper methods."""
        subscription = ModelViewSubscription.initialize(
            user=self.user,
            model_name=self.model_name,
            ast_query=self.ast_query,
            response_data=self.response_data
        )
        
        # Test deactivate
        self.assertTrue(subscription.is_active)
        subscription.deactivate()
        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)
        
        # Test reactivate
        subscription.has_error = True  # Set error state to test clearing
        subscription.reactivate()
        subscription.refresh_from_db()
        self.assertTrue(subscription.is_active)
        self.assertFalse(subscription.has_error)

    def test_channel_name_consistency(self):
        """Test that channel names are generated consistently for the same query."""
        subscription1 = ModelViewSubscription.initialize(
            user=self.user,
            model_name=self.model_name,
            ast_query=self.ast_query,
            response_data=self.response_data
        )
        
        # Create another subscription with same query (different user to avoid unique constraint)
        subscription2 = ModelViewSubscription.initialize(
            user=self.user2,
            model_name=self.model_name,
            ast_query=self.ast_query,
            response_data=self.response_data
        )
        
        # Channel names should be identical (same query)
        self.assertEqual(subscription1.channel_name, subscription2.channel_name)
        
        # But different from a subscription with different query
        different_ast = {
            "query": {
                "type": "get",
                "pk": 1
            },
            "serializerOptions": {}
        }
        
        subscription3 = ModelViewSubscription.initialize(
            user=self.user,
            model_name=self.model_name,
            ast_query=different_ast,
            response_data=self.response_data
        )
        
        self.assertNotEqual(subscription1.channel_name, subscription3.channel_name)


class ModelViewSubscriptionIntegrationTest(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.force_authenticate(user=self.user)
        
        # Create test data
        self.related1 = DummyRelatedModel.objects.create(name="Related1")
        self.dummy1 = DummyModel.objects.create(name="TestA", value=10, related=self.related1)
        self.dummy2 = DummyModel.objects.create(name="TestB", value=20, related=self.related1)
        
        self.model_name = "django_app.DummyModel"
        self.url = reverse("statezero:model_view", args=[self.model_name])
    
    def test_rerun_no_change(self):
        """Test that rerun returns False when data hasn't changed."""
        # Use the exact structure from frontend debug output
        ast_query = {
            "query": {
                "type": "list",
                "filter": {"type": "filter", "conditions": {"value__gte": 10}},
                "search": None,
                "aggregations": []
            },
            "serializerOptions": {}
        }
        
        # Make actual API call to get real initial response
        url = reverse("statezero:model_view", args=[self.model_name])
        payload = {"ast": ast_query}
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        initial_response_data = response.data
        
        # Create subscription with the full AST structure
        live_view = ModelViewSubscription.initialize(
            user=self.user,
            model_name=self.model_name,
            ast_query=ast_query,
            response_data=initial_response_data
        )
        
        original_hash = live_view.response_hash
        
        # Rerun without making any data changes
        has_changed = live_view.rerun()
        
        self.assertFalse(has_changed)
        self.assertEqual(live_view.response_hash, original_hash)
        self.assertFalse(live_view.has_error)

    def test_rerun_detects_change(self):
        """Test that rerun detects when data changes."""
        ast_query = {
            "query": {
                "type": "list",
                "filter": {"type": "filter", "conditions": {"value__gte": 10}},
                "search": None,
                "aggregations": []
            },
            "serializerOptions": {}
        }
        
        # Make actual API call to get real initial response
        url = reverse("statezero:model_view", args=[self.model_name])
        payload = {"ast": ast_query}
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        initial_response_data = response.data
        
        # Create subscription with the full AST structure
        live_view = ModelViewSubscription.initialize(
            user=self.user,
            model_name=self.model_name,
            ast_query=ast_query,
            response_data=initial_response_data
        )
        
        original_hash = live_view.response_hash
        
        # Add new instance that matches the filter (value >= 10)
        DummyModel.objects.create(name="TestC", value=30, related=self.related1)
        
        # Rerun should detect the change
        has_changed = live_view.rerun()
        
        self.assertTrue(has_changed)
        self.assertNotEqual(live_view.response_hash, original_hash)
        self.assertFalse(live_view.has_error)

    def test_rerun_only_relevant_changes(self):
        """Test that only relevant changes trigger hash updates."""
        # Filter for value == 20 (only TestB should match)
        ast_query = {
            "query": {
                "type": "list",
                "filter": {"type": "filter", "conditions": {"value": 20}},
                "search": None,
                "aggregations": []
            },
            "serializerOptions": {}
        }
        
        # Make actual API call to get real initial response
        url = reverse("statezero:model_view", args=[self.model_name])
        payload = {"ast": ast_query}
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        initial_response_data = response.data
        
        # FIX: Handle the nested data structure correctly
        response_data = initial_response_data.get("data", {})
        data_ids = response_data.get("data", [])  # Get data.data, not just data
        included = response_data.get("included", {})
        model_data = included.get("django_app.dummymodel", {})
        
        # Should only have one record (TestB with value=20)
        self.assertEqual(len(data_ids), 1)
        record_id = data_ids[0]
        record = model_data.get(record_id, {})  # Use the integer key directly
        self.assertEqual(record.get("name"), "TestB")
        self.assertEqual(record.get("value"), 20)
        
        # Create subscription with the full AST structure
        live_view = ModelViewSubscription.initialize(
            user=self.user,
            model_name=self.model_name,
            ast_query=ast_query,
            response_data=initial_response_data
        )
        
        original_hash = live_view.response_hash
        
        # Change TestA (value=10) to value=5 - should NOT affect filtered results
        self.dummy1.value = 5
        self.dummy1.save()
        
        has_changed = live_view.rerun()
        self.assertFalse(has_changed)
        self.assertEqual(live_view.response_hash, original_hash)
        
        # Change TestB (value=20) to value=25 - should affect filtered results
        self.dummy2.value = 25
        self.dummy2.save()
        
        has_changed = live_view.rerun()
        self.assertTrue(has_changed)
        self.assertNotEqual(live_view.response_hash, original_hash)

    def test_multiple_subscriptions_per_user(self):
        """Test that a user can have multiple active subscriptions for different queries."""
        # First subscription - filter for value >= 10
        ast_query1 = {
            "query": {
                "type": "list",
                "filter": {"type": "filter", "conditions": {"value__gte": 10}},
                "search": None,
                "aggregations": []
            },
            "serializerOptions": {}
        }
        
        # Second subscription - filter for value <= 15
        ast_query2 = {
            "query": {
                "type": "list",
                "filter": {"type": "filter", "conditions": {"value__lte": 15}},
                "search": None,
                "aggregations": []
            },
            "serializerOptions": {}
        }
        
        # Create both subscriptions
        subscription1, created1 = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=ast_query1,
            response_data={"data": "response1"}
        )
        
        subscription2, created2 = ModelViewSubscription.update_or_create_subscription(
            user=self.user,
            model_name=self.model_name,
            ast_query=ast_query2,
            response_data={"data": "response2"}
        )
        
        self.assertTrue(created1)
        self.assertTrue(created2)
        self.assertNotEqual(subscription1.id, subscription2.id)
        self.assertNotEqual(subscription1.channel_name, subscription2.channel_name)
        
        # Both should be active for the same user
        user_subscriptions = ModelViewSubscription.objects.filter(
            user=self.user,
            is_active=True
        )
        self.assertEqual(user_subscriptions.count(), 2)