"""
Tests for subscription processor logic - end-to-end tests.
"""
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from tests.django_app.models import DummyModel, ComprehensiveModel
from statezero.adaptors.django.models import QuerySubscription
from statezero.core.query_cache import current_canonical_id


class SubscriptionProcessorTestCase(TransactionTestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        current_canonical_id.set("test-txn")

    def tearDown(self):
        """Clean up after tests."""
        QuerySubscription.objects.all().delete()
        DummyModel.objects.all().delete()
        ComprehensiveModel.objects.all().delete()
        current_canonical_id.set(None)

    def test_new_instance_marks_subscription_dirty(self):
        """Test that creating a new instance marks subscription as needing rerun."""
        # Step 1: Create initial data
        obj1 = DummyModel.objects.create(name="Initial")

        # Step 2: Query and subscribe
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, {"ast": {"query": {"type": "read"}}}, format="json")
        self.assertEqual(response.status_code, 200)

        subscribe_url = reverse("statezero:subscribe", args=["django_app.DummyModel"])
        sub_response = self.client.post(subscribe_url, {"ast": {"query": {"type": "read"}}}, format="json")
        self.assertEqual(sub_response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=sub_response.data["subscription_id"])
        self.assertFalse(subscription.needs_rerun)

        # Step 3: Create new instance
        obj2 = DummyModel.objects.create(name="New")

        # Step 4: Verify subscription marked dirty
        subscription.refresh_from_db()
        self.assertTrue(subscription.needs_rerun)

    def test_updating_existing_instance_marks_subscription_dirty(self):
        """Test that updating an existing instance marks subscription as needing rerun."""
        # Step 1: Create initial data
        obj1 = DummyModel.objects.create(name="Initial")

        # Step 2: Query and subscribe
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, {"ast": {"query": {"type": "read"}}}, format="json")
        self.assertEqual(response.status_code, 200)

        subscribe_url = reverse("statezero:subscribe", args=["django_app.DummyModel"])
        sub_response = self.client.post(subscribe_url, {"ast": {"query": {"type": "read"}}}, format="json")
        self.assertEqual(sub_response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=sub_response.data["subscription_id"])
        self.assertFalse(subscription.needs_rerun)

        # Step 3: Update existing instance
        obj1.name = "Updated"
        obj1.save()

        # Step 4: Verify subscription marked dirty
        subscription.refresh_from_db()
        self.assertTrue(subscription.needs_rerun)

    def test_irrelevant_instance_does_not_mark_subscription_dirty(self):
        """Test that instances not matching namespace don't mark subscription dirty."""
        # Step 1: Create initial data with specific char_field
        obj1 = ComprehensiveModel.objects.create(
            char_field="target_value",
            text_field="test",
            int_field=1,
            decimal_field="10.50"
        )

        # Step 2: Query and subscribe with namespace filter
        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        query_ast = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"char_field": "target_value"}
                    }
                }
            }
        }
        response = self.client.post(url, query_ast, format="json")
        self.assertEqual(response.status_code, 200)

        subscribe_url = reverse("statezero:subscribe", args=["django_app.ComprehensiveModel"])
        sub_response = self.client.post(subscribe_url, query_ast, format="json")
        self.assertEqual(sub_response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=sub_response.data["subscription_id"])
        self.assertFalse(subscription.needs_rerun)
        self.assertEqual(subscription.namespace, {"char_field": "target_value"})

        # Step 3: Create instance with different char_field (doesn't match namespace)
        obj2 = ComprehensiveModel.objects.create(
            char_field="other_value",
            text_field="test",
            int_field=2,
            decimal_field="20.50"
        )

        # Step 4: Verify subscription NOT marked dirty
        subscription.refresh_from_db()
        self.assertFalse(subscription.needs_rerun)

    def test_matching_namespace_marks_subscription_dirty(self):
        """Test that instances matching namespace DO mark subscription dirty."""
        # Step 1: Create initial data with specific char_field
        obj1 = ComprehensiveModel.objects.create(
            char_field="target_value",
            text_field="test",
            int_field=1,
            decimal_field="10.50"
        )

        # Step 2: Query and subscribe with namespace filter
        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        query_ast = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"char_field": "target_value"}
                    }
                }
            }
        }
        response = self.client.post(url, query_ast, format="json")
        self.assertEqual(response.status_code, 200)

        subscribe_url = reverse("statezero:subscribe", args=["django_app.ComprehensiveModel"])
        sub_response = self.client.post(subscribe_url, query_ast, format="json")
        self.assertEqual(sub_response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=sub_response.data["subscription_id"])
        self.assertFalse(subscription.needs_rerun)

        # Step 3: Create instance with matching char_field
        obj2 = ComprehensiveModel.objects.create(
            char_field="target_value",
            text_field="test",
            int_field=2,
            decimal_field="20.50"
        )

        # Step 4: Verify subscription marked dirty
        subscription.refresh_from_db()
        self.assertTrue(subscription.needs_rerun)

    def test_aggregate_query_always_marks_dirty(self):
        """Test that aggregate queries are always marked dirty on any change."""
        # Step 1: Create initial data
        obj1 = DummyModel.objects.create(name="Initial")

        # Step 2: Query and subscribe to aggregate (count)
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        query_ast = {
            "ast": {
                "query": {
                    "type": "aggregate",
                    "aggregations": [{"function": "count", "alias": "total"}]
                }
            }
        }
        response = self.client.post(url, query_ast, format="json")
        self.assertEqual(response.status_code, 200)

        subscribe_url = reverse("statezero:subscribe", args=["django_app.DummyModel"])
        sub_response = self.client.post(subscribe_url, query_ast, format="json")
        self.assertEqual(sub_response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=sub_response.data["subscription_id"])
        self.assertEqual(subscription.query_type, "aggregate")
        self.assertFalse(subscription.needs_rerun)

        # Step 3: Create new instance
        obj2 = DummyModel.objects.create(name="New")

        # Step 4: Verify subscription marked dirty (aggregates always rerun)
        subscription.refresh_from_db()
        self.assertTrue(subscription.needs_rerun)

    def test_already_dirty_subscription_not_reprocessed(self):
        """Test that already dirty subscriptions are not queried again."""
        # Step 1: Create initial data
        obj1 = DummyModel.objects.create(name="Initial")

        # Step 2: Query and subscribe
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, {"ast": {"query": {"type": "read"}}}, format="json")
        self.assertEqual(response.status_code, 200)

        subscribe_url = reverse("statezero:subscribe", args=["django_app.DummyModel"])
        sub_response = self.client.post(subscribe_url, {"ast": {"query": {"type": "read"}}}, format="json")
        self.assertEqual(sub_response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=sub_response.data["subscription_id"])

        # Step 3: Manually mark as dirty
        subscription.needs_rerun = True
        subscription.save()

        # Step 4: Create new instance
        obj2 = DummyModel.objects.create(name="New")

        # Step 5: Verify it's still dirty (not reprocessed, just stays dirty)
        subscription.refresh_from_db()
        self.assertTrue(subscription.needs_rerun)

    def test_bulk_operation_marks_subscription_dirty(self):
        """Test that bulk operations mark subscriptions correctly."""
        # Step 1: Create initial data
        obj1 = DummyModel.objects.create(name="Initial1")
        obj2 = DummyModel.objects.create(name="Initial2")

        # Step 2: Query and subscribe
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, {"ast": {"query": {"type": "read"}}}, format="json")
        self.assertEqual(response.status_code, 200)

        subscribe_url = reverse("statezero:subscribe", args=["django_app.DummyModel"])
        sub_response = self.client.post(subscribe_url, {"ast": {"query": {"type": "read"}}}, format="json")
        self.assertEqual(sub_response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=sub_response.data["subscription_id"])
        self.assertFalse(subscription.needs_rerun)

        # Step 3: Bulk update via StateZero API (copy frontend format)
        bulk_update_ast = {
            "ast": {
                "query": {
                    "type": "update",
                    "filter": {
                        "type": "filter",
                        "conditions": {"name__startswith": "Initial"}
                    },
                    "data": {"value": 100}
                }
            }
        }
        update_response = self.client.post(url, bulk_update_ast, format="json")
        self.assertEqual(update_response.status_code, 200)

        # Step 4: Verify subscription marked dirty
        subscription.refresh_from_db()
        self.assertTrue(subscription.needs_rerun)
