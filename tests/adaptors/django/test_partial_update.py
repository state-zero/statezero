"""
Test for partial update with required fields not in editable_fields.
This reproduces the issue where updating an instance fails when required fields
are not included in the editable_fields permission.
"""

import json
from datetime import date
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from statezero.adaptors.django.permissions import AllowAllPermission
from statezero.core.types import ActionType
from tests.django_app.models import RatePlan, DailyRate
from statezero.adaptors.django.config import registry


class PartialUpdateTest(APITestCase):
    def setUp(self):
        # Create and log in a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create test data: DailyRate has required fields: rate_plan, date
        # Plus a unique constraint on (rate_plan, date)
        self.rate_plan = RatePlan.objects.create(name="Standard Rate")
        self.daily_rate = DailyRate.objects.create(
            rate_plan=self.rate_plan,  # Required FK
            date=date(2024, 1, 1),  # Required field
            price=100.00  # Optional field
        )

    def test_partial_update_with_unique_constraint_fields(self):
        """
        Test that partial updates work when required fields with unique constraints
        are not in editable_fields.

        Scenario: DailyRate has 'rate_plan' and 'date' as required fields with a
        unique constraint. Permission only allows editing 'price' field.
        When updating just 'price', the update should succeed even though
        'rate_plan' and 'date' are required but not included in the update data.
        """

        # Define a permission that only allows editing 'price', not the required constraint fields
        class PartialUpdatePermission(AllowAllPermission):
            def allowed_actions(self, request, model):
                return {
                    ActionType.CREATE,
                    ActionType.READ,
                    ActionType.UPDATE,
                    ActionType.DELETE,
                }

            def editable_fields(self, request, model):
                # Only allow optional fields to be edited
                # NOT the required fields 'rate_plan' or 'date' which have a unique constraint
                # This simulates a permission where the unique constraint fields can't be changed
                return {"price", "min_stay_arrival", "min_stay_through", "max_stay",
                        "closed_to_arrival", "closed_to_departure", "stop_sell"}

            def create_fields(self, request, model):
                # For create, allow all fields
                return "__all__"

            def readable_fields(self, request, model):
                return "__all__"

        # Override permissions temporarily
        original_config = registry.get_config(DailyRate)
        original_permissions = original_config._permissions
        original_config._permissions = [PartialUpdatePermission]

        try:
            url = reverse("statezero:model_view", args=["django_app.DailyRate"])

            # Simulate what the frontend client sends when calling instance.save()
            # after modifying just the 'price' field
            # This uses update_instance operation which is what .save() uses
            update_payload = {
                "ast": {
                    "query": {
                        "type": "update_instance",
                        "filter": {
                            "type": "filter",
                            "conditions": {"id": self.daily_rate.id}
                        },
                        "data": {
                            "price": "150.00"  # Only updating 'price', not 'rate_plan' or 'date'
                        }
                    }
                }
            }

            response = self.client.post(url, data=update_payload, format="json")

            # This should succeed with a partial update
            # Bug: Currently fails with: {"rate_plan": ["This field is required."], "date": ["This field is required."]}
            self.assertEqual(
                response.status_code,
                200,
                f"Partial update failed with response: {response.data}"
            )

            # Verify the update was successful
            self.daily_rate.refresh_from_db()
            self.assertEqual(float(self.daily_rate.price), 150.00)
            # Required fields should remain unchanged
            self.assertEqual(self.daily_rate.rate_plan, self.rate_plan)
            self.assertEqual(self.daily_rate.date, date(2024, 1, 1))

        finally:
            # Restore original permissions
            original_config._permissions = original_permissions
