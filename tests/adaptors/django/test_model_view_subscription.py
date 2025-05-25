from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import TestCase
from rest_framework.test import APITestCase
from statezero.adaptors.django.models import ModelViewSubscription
from tests.django_app.models import DummyModel, DummyRelatedModel

User = get_user_model()

class ModelViewSubscriptionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
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
    
    def test_initialize(self):
        """Test creating a live model view."""
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