"""
Test to see the actual response structure from a query.
"""
import json
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from django.urls import reverse
from tests.django_app.models import DummyModel, DummyRelatedModel
from statezero.core.query_cache import current_canonical_id


class ResponseStructureTest(TestCase):
    """Test to inspect actual response structure."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        current_canonical_id.set("txn-structure-test")

    def tearDown(self):
        current_canonical_id.set(None)

    def test_see_response_structure(self):
        """Execute a query and print the response structure."""
        # Create some test data
        related1 = DummyRelatedModel.objects.create(name="Related1")
        related2 = DummyRelatedModel.objects.create(name="Related2")

        obj1 = DummyModel.objects.create(name="TestA", value=100, related=related1)
        obj2 = DummyModel.objects.create(name="TestB", value=200, related=related2)

        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")

        print("\n" + "="*80)
        print("RESPONSE STRUCTURE:")
        print("="*80)
        print(json.dumps(response.data, indent=2))
        print("="*80)

        # Also check the keys
        print("\nTop-level keys:", list(response.data.keys()))
        if "data" in response.data:
            print("'data' keys:", list(response.data["data"].keys()))
        if "detail" in response.data:
            print("'detail' type:", type(response.data["detail"]))
            if isinstance(response.data["detail"], dict):
                print("'detail' sample keys:", list(response.data["detail"].keys())[:5])

        # Clean up
        obj1.delete()
        obj2.delete()
        related1.delete()
        related2.delete()
