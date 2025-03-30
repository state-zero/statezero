import json

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from tests.django_app.models import (DeepModelLevel1, DeepModelLevel2,
                                     DeepModelLevel3, DummyModel,
                                     DummyRelatedModel)

User = get_user_model()


class FilterAndExcludeIntegrationTest(APITestCase):
    def setUp(self):
        # Create a test user.
        self.user = User.objects.create_user(username="testuser", password="password")
        # Instead of just login, force authentication on the test client.
        self.client.force_authenticate(user=self.user)
        # Create a related model instance for FK relationships.
        self.related1 = DummyRelatedModel.objects.create(name="Related1")
        self.related2 = DummyRelatedModel.objects.create(name="Related2")
        # Create several DummyModel instances.
        DummyModel.objects.create(name="TestA", value=10, related=self.related1)
        DummyModel.objects.create(name="TestB", value=20, related=self.related1)
        DummyModel.objects.create(name="TestC", value=30, related=self.related2)
        DummyModel.objects.create(name="TestD", value=40, related=self.related2)

        # Create nested models for deep filtering test
        # First, create DeepModelLevel3 with name="Deep3"
        deep3 = DeepModelLevel3.objects.create(name="Deep3")
        # Next, create DeepModelLevel2 that links to deep3
        deep2 = DeepModelLevel2.objects.create(name="Level2", level3=deep3)
        # Finally, create DeepModelLevel1 that links to deep2
        DeepModelLevel1.objects.create(name="Level1", level2=deep2)

    def test_basic_filter(self):
        """
        Test that a simple filter returns only the matching record(s).
        """
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {"type": "filter", "conditions": {"value": 20}},
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.data.get("data", [])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0].get("name"), "TestB")

    def test_filter_with_q_objects_or(self):
        """
        Test that filtering with Q objects using OR returns records matching either condition.
        For example, return records with value 10 OR value 30.
        """
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {},
                        "Q": [{"value": 10}, {"value": 30}],
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.data.get("data", [])
        # Expect TestA and TestC
        values = {item.get("value") for item in data}
        self.assertSetEqual(values, {10, 30})

    def test_filter_with_q_objects_and(self):
        """
        Test that filtering with Q objects using an AND combination returns only records
        that satisfy all conditions.
        For instance, if we require name starting with "Test" AND value less than 40.
        """
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"name__startswith": "Test"},
                        "Q": [{"value__lt": 40}],
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.data.get("data", [])
        # TestA (10), TestB (20), TestC (30) all have value < 40. If additional conditions exist in the plain filter,
        # the final intersection should be verified.
        # In this example, the plain filter only ensures name starts with "Test", which all do.
        self.assertEqual(len(data), 3)

    def test_exclude_basic(self):
        """
        Test that using exclude removes matching records.
        For example, exclude records where value equals 10 should remove TestA.
        """
        # Build an AST with an "exclude" node.
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    # Instead of a top-level "filter", we include an "exclude" modifier.
                    "exclude": {
                        "type": "exclude",
                        "child": {"type": "filter", "conditions": {"value": 10}},
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.data.get("data", [])
        # Expect that the record with value 10 (TestA) is excluded.
        values = {item.get("value") for item in data}
        self.assertNotIn(10, values)
        # With four initial records, we expect three remaining.
        self.assertEqual(len(data), 3)

    def test_chained_filter_and_exclude(self):
        """
        Test that chaining a filter with an exclude returns the correct subset.
        For example, filter records with name starting with "Test" (which are all),
        then exclude those with value greater than or equal to 30.
        """
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"name__startswith": "Test"},
                    },
                    "exclude": {
                        "type": "exclude",
                        "child": {"type": "filter", "conditions": {"value__gte": 30}},
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.data.get("data", [])
        # With TestA (10) and TestB (20) expected to remain.
        expected_values = {10, 20}
        result_values = {item.get("value") for item in data}
        self.assertSetEqual(result_values, expected_values)

    def test_exclude_with_q_objects(self):
        """
        Test that using exclude with Q objects works correctly.
        For example, exclude records where (value equals 10 OR value equals 40).
        """
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "exclude": {
                        "type": "exclude",
                        "child": {
                            "type": "or",
                            "children": [
                                {"type": "filter", "conditions": {"value": 10}},
                                {"type": "filter", "conditions": {"value": 40}},
                            ],
                        },
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.data.get("data", [])
        # Expect that records with value 10 (TestA) and 40 (TestD) are excluded.
        values = {item.get("value") for item in data}
        self.assertFalse(10 in values)
        self.assertFalse(40 in values)
        # Only TestB (20) and TestC (30) remain.
        self.assertSetEqual(values, {20, 30})

    def test_filter_exclude_special_characters(self):
        """
        Test that filters and excludes correctly handle field values with special characters.
        """
        # Create an additional instance with special characters in the name.
        DummyModel.objects.create(name="Special!@#$%^", value=55, related=self.related1)
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"name": "Special!@#$%^"},
                    },
                    "exclude": {
                        "type": "exclude",
                        "child": {"type": "filter", "conditions": {"value": 55}},
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.data.get("data", [])
        # The record should be filtered in, then excluded because its value is 55.
        self.assertEqual(len(data), 0)

    def test_deeply_nested_field_filtering(self):
        """
        Test that filtering using a deeply nested field lookup works correctly.
        For example, filter DeepModelLevel1 instances whose related level2's related level3's name is "Deep3".
        """
        # Build an AST payload that filters on a nested field.
        # Here we assume DeepModelLevel1 has a relationship field named "level2",
        # and DeepModelLevel2 has a relationship field named "level3".
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"level2__level3__name": "Deep3"},
                    },
                },
                "serializerOptions": {
                    "depth": 4,  # Include nested relationships up to 3 levels deep
                    "fields": ["id", "name", "level2", "level2__level3"],
                },
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DeepModelLevel1"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.data.get("data", [])
        # Expect at least one DeepModelLevel1 instance whose nested level3's name equals "Deep3"
        self.assertTrue(
            len(data) > 0, "At least one deep model instance should be returned"
        )

        # Verify that for each returned instance, the nested level3 name is "Deep3".
        # This assumes the serializer returns nested related fields as dictionaries.
        for instance in data:
            # Depending on your serializer, level2 may be a nested object.
            level2 = instance.get("level2", {})
            self.assertIsInstance(level2, dict, "level2 should be a dictionary")
            level3 = level2.get("level3", {})
            self.assertIsInstance(level3, dict, "level3 should be a dictionary")
            self.assertEqual(
                level3.get("name"),
                "Deep3",
                "Deeply nested field should match the filter",
            )
