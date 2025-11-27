"""
Integration tests for MoneyField with query optimizer.
Tests that MoneyField serialization works correctly when fields are explicitly requested
through the full StateZero request flow with query optimization.
"""
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from tests.django_app.models import ComprehensiveModel

User = get_user_model()


class MoneyFieldIntegrationTest(APITestCase):
    """Test MoneyField serialization through the full request flow"""

    def setUp(self):
        from djmoney.money import Money

        # Create a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.force_authenticate(user=self.user)

        # Create ComprehensiveModel instances with MoneyField
        self.instance1 = ComprehensiveModel.objects.create(
            char_field="Product A",
            text_field="Description A",
            int_field=100,
            bool_field=True,
            datetime_field=timezone.now(),
            decimal_field=Decimal("99.99"),
            json_field={"category": "electronics"},
            money_field=Money(150.50, "USD")
        )

        self.instance2 = ComprehensiveModel.objects.create(
            char_field="Product B",
            text_field="Description B",
            int_field=200,
            bool_field=False,
            datetime_field=timezone.now(),
            decimal_field=Decimal("199.99"),
            json_field={"category": "furniture"},
            money_field=Money(299.99, "EUR")
        )

    def test_money_field_with_explicit_fields(self):
        """
        Test that MoneyField serializes correctly when explicitly requested
        through the full request flow with query optimization.
        """
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "fetch": {
                        "fields": ["id", "char_field", "money_field"]
                    }
                }
            }
        }

        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)

        # Verify the response structure
        data = response.data["data"]
        self.assertIn("data", data)
        self.assertIn("included", data)
        self.assertIn("django_app.comprehensivemodel", data["included"])

        # Verify we have data for both instances
        included_data = data["included"]["django_app.comprehensivemodel"]
        self.assertEqual(len(included_data), 2)

        # Verify money_field is serialized correctly for both instances
        for instance_id, instance_data in included_data.items():
            self.assertIn("money_field", instance_data)
            money_data = instance_data["money_field"]

            # MoneyField should be a dict with amount and currency
            self.assertIsInstance(money_data, dict)
            self.assertIn("amount", money_data)
            self.assertIn("currency", money_data)

        # Verify specific values
        instance1_data = included_data[self.instance1.id]
        self.assertEqual(instance1_data["money_field"]["amount"], "150.50")
        self.assertEqual(instance1_data["money_field"]["currency"], "USD")
        self.assertEqual(instance1_data["char_field"], "Product A")

        instance2_data = included_data[self.instance2.id]
        self.assertEqual(instance2_data["money_field"]["amount"], "299.99")
        self.assertEqual(instance2_data["money_field"]["currency"], "EUR")
        self.assertEqual(instance2_data["char_field"], "Product B")

    def test_money_field_with_multiple_fields(self):
        """
        Test that MoneyField works correctly alongside other field types
        when explicitly requested through the full request flow.
        """
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "fetch": {
                        "fields": [
                            "id",
                            "char_field",
                            "int_field",
                            "decimal_field",
                            "money_field",
                            "bool_field"
                        ]
                    }
                }
            }
        }

        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)

        included_data = response.data["data"]["included"]["django_app.comprehensivemodel"]
        instance1_data = included_data[self.instance1.id]

        # Verify all requested fields are present
        self.assertIn("char_field", instance1_data)
        self.assertIn("int_field", instance1_data)
        self.assertIn("decimal_field", instance1_data)
        self.assertIn("money_field", instance1_data)
        self.assertIn("bool_field", instance1_data)

        # Verify field values are correct
        self.assertEqual(instance1_data["char_field"], "Product A")
        self.assertEqual(instance1_data["int_field"], 100)
        self.assertEqual(instance1_data["decimal_field"], "99.99")
        self.assertEqual(instance1_data["bool_field"], True)
        self.assertEqual(instance1_data["money_field"]["amount"], "150.50")
        self.assertEqual(instance1_data["money_field"]["currency"], "USD")

    def test_money_field_with_filter(self):
        """
        Test that MoneyField works correctly when combined with filtering.
        """
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"char_field": "Product A"}
                    },
                    "fetch": {
                        "fields": ["id", "char_field", "money_field"]
                    }
                }
            }
        }

        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)

        # Should only return one instance
        included_data = response.data["data"]["included"]["django_app.comprehensivemodel"]
        self.assertEqual(len(included_data), 1)

        # Verify it's the correct instance with correct money_field
        instance_data = included_data[self.instance1.id]
        self.assertEqual(instance_data["char_field"], "Product A")
        self.assertEqual(instance_data["money_field"]["amount"], "150.50")
        self.assertEqual(instance_data["money_field"]["currency"], "USD")

    def test_money_field_bulk_update(self):
        """
        Test that updating a MoneyField works correctly.
        This tests the fix for KeyError 'price_currency' when using .only() with MoneyField.
        """
        payload = {
            "ast": {
                "query": {
                    "type": "update",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.instance1.id}
                    },
                    "data": {
                        "money_field": {"amount": "250.00", "currency": "GBP"}
                    }
                }
            }
        }

        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200, f"Update failed: {response.data}")

        # Verify the update was successful
        self.instance1.refresh_from_db()
        self.assertEqual(str(self.instance1.money_field.amount), "250.00")
        self.assertEqual(str(self.instance1.money_field.currency), "GBP")
