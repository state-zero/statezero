"""
Tests for the SubscribeView endpoint.
"""
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from statezero.adaptors.django.models import QuerySubscription
from statezero.core.query_cache import current_canonical_id


class SubscribeViewTestCase(TransactionTestCase):
    """Test the subscribe endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        # Clean up
        QuerySubscription.objects.all().delete()
        User.objects.all().delete()

        # Create test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client = APIClient()

        # Set canonical ID for consistent cache keys
        current_canonical_id.set("txn-subscribe-test")

    def tearDown(self):
        """Clean up after tests."""
        QuerySubscription.objects.all().delete()
        User.objects.all().delete()
        current_canonical_id.set(None)

    def test_subscribe_authenticated_user_creates_subscription(self):
        """Test that authenticated user creates a new subscription."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("cache_key", response.data)
        self.assertIn("subscription_id", response.data)
        self.assertTrue(response.data["created"])

        # Verify subscription was created
        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        self.assertIn(self.user, subscription.users.all())
        self.assertFalse(subscription.anonymous_users_allowed)

    def test_subscribe_anonymous_user_creates_subscription(self):
        """Test that anonymous user creates a subscription with flag set (skipped if permission denies anonymous)."""
        # Check if anonymous users are allowed
        from django.conf import settings
        from django.utils.module_loading import import_string

        default_permission = "rest_framework.permissions.AllowAny"
        permission_class = import_string(getattr(settings, "STATEZERO_VIEW_ACCESS_CLASS", default_permission))

        if permission_class.__name__ != "AllowAny":
            self.skipTest("This test requires AllowAny permission class")

        # Don't authenticate
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("cache_key", response.data)
        self.assertIn("subscription_id", response.data)
        self.assertTrue(response.data["created"])

        # Verify subscription was created with anonymous flag
        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        self.assertTrue(subscription.anonymous_users_allowed)
        self.assertEqual(subscription.users.count(), 0)

    def test_subscribe_existing_subscription_adds_user(self):
        """Test that subscribing to existing query adds user to subscription."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # First request creates subscription
        response1 = self.client.post(url, data=payload, format="json")
        self.assertEqual(response1.status_code, 200)
        self.assertTrue(response1.data["created"])
        subscription_id = response1.data["subscription_id"]

        # Second request with same query should reuse subscription
        response2 = self.client.post(url, data=payload, format="json")
        self.assertEqual(response2.status_code, 200)
        self.assertFalse(response2.data["created"])
        self.assertEqual(response2.data["subscription_id"], subscription_id)

        # User should still be in subscribers
        subscription = QuerySubscription.objects.get(id=subscription_id)
        self.assertIn(self.user, subscription.users.all())
        self.assertEqual(subscription.users.count(), 1)

    def test_subscribe_multiple_users_same_query(self):
        """Test that multiple users can subscribe to the same query."""
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # User 1 subscribes
        user1 = User.objects.create_user(username="user1", password="password")
        self.client.force_authenticate(user=user1)
        response1 = self.client.post(url, data=payload, format="json")
        self.assertEqual(response1.status_code, 200)
        subscription_id = response1.data["subscription_id"]

        # User 2 subscribes to same query
        user2 = User.objects.create_user(username="user2", password="password")
        self.client.force_authenticate(user=user2)
        response2 = self.client.post(url, data=payload, format="json")
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.data["subscription_id"], subscription_id)

        # Both users should be in subscription
        subscription = QuerySubscription.objects.get(id=subscription_id)
        self.assertEqual(subscription.users.count(), 2)
        self.assertIn(user1, subscription.users.all())
        self.assertIn(user2, subscription.users.all())

    def test_subscribe_different_queries_different_subscriptions(self):
        """Test that different queries create different subscriptions."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        # Query 1: Read all
        payload1 = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        response1 = self.client.post(url, data=payload1, format="json")
        self.assertEqual(response1.status_code, 200)
        cache_key1 = response1.data["cache_key"]
        subscription_id1 = response1.data["subscription_id"]

        # Query 2: Read with filter
        payload2 = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"name": "TestA"}
                    }
                }
            }
        }

        response2 = self.client.post(url, data=payload2, format="json")
        self.assertEqual(response2.status_code, 200)
        cache_key2 = response2.data["cache_key"]
        subscription_id2 = response2.data["subscription_id"]

        # Should be different subscriptions
        self.assertNotEqual(cache_key1, cache_key2)
        self.assertNotEqual(subscription_id1, subscription_id2)

        # Both subscriptions should exist
        self.assertEqual(QuerySubscription.objects.count(), 2)

    def test_subscribe_stores_ast(self):
        """Test that the AST is stored in the subscription."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"value": 10}
                    }
                },
                "serializerOptions": {
                    "limit": 10
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        # The full request payload is stored (for proxying to ModelView later)
        self.assertEqual(subscription.ast, payload)

    def test_subscribe_returns_full_cache_key(self):
        """Test that the returned cache key has the correct format."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)

        cache_key = response.data["cache_key"]
        self.assertTrue(cache_key.startswith("statezero:query:"))

        # Verify the hash portion matches the subscription
        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        expected_cache_key = f"statezero:query:{subscription.hashed_cache_key}"
        self.assertEqual(cache_key, expected_cache_key)

    def test_subscribe_aggregate_query(self):
        """Test subscribing to an aggregate query."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "count",
                    "field": "id"
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("cache_key", response.data)
        self.assertIn("subscription_id", response.data)

        # Verify subscription was created
        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        self.assertIn(self.user, subscription.users.all())

    def test_subscribe_with_pagination(self):
        """Test subscribing with pagination options."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                },
                "serializerOptions": {
                    "limit": 10,
                    "offset": 20
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("cache_key", response.data)

        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        # The full request payload is stored
        self.assertEqual(subscription.ast["ast"]["serializerOptions"]["limit"], 10)
        self.assertEqual(subscription.ast["ast"]["serializerOptions"]["offset"], 20)

    def test_subscribe_anonymous_then_authenticated(self):
        """Test that anonymous subscription is updated when user authenticates (skipped if permission denies anonymous)."""
        # Check if anonymous users are allowed
        from django.conf import settings
        from django.utils.module_loading import import_string

        default_permission = "rest_framework.permissions.AllowAny"
        permission_class = import_string(getattr(settings, "STATEZERO_VIEW_ACCESS_CLASS", default_permission))

        if permission_class.__name__ != "AllowAny":
            self.skipTest("This test requires AllowAny permission class")

        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # First subscribe as anonymous
        response1 = self.client.post(url, data=payload, format="json")
        self.assertEqual(response1.status_code, 200)
        subscription_id = response1.data["subscription_id"]

        subscription = QuerySubscription.objects.get(id=subscription_id)
        self.assertTrue(subscription.anonymous_users_allowed)
        self.assertEqual(subscription.users.count(), 0)

        # Then subscribe as authenticated user
        self.client.force_authenticate(user=self.user)
        response2 = self.client.post(url, data=payload, format="json")
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.data["subscription_id"], subscription_id)

        # Should now have both anonymous flag and user
        subscription.refresh_from_db()
        self.assertTrue(subscription.anonymous_users_allowed)
        self.assertEqual(subscription.users.count(), 1)
        self.assertIn(self.user, subscription.users.all())

    def test_subscribe_has_subscribers_method(self):
        """Test the has_subscribers() method."""
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # Subscribe as authenticated user
        self.client.force_authenticate(user=self.user)
        response = self.client.post(url, data=payload, format="json")
        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])

        self.assertTrue(subscription.has_subscribers())

        # Remove user
        subscription.users.clear()
        self.assertFalse(subscription.has_subscribers())

        # Add anonymous flag
        subscription.anonymous_users_allowed = True
        subscription.save()
        self.assertTrue(subscription.has_subscribers())

    def test_subscribe_no_canonical_id_fails_gracefully(self):
        """Test that subscribe handles missing canonical_id gracefully."""
        current_canonical_id.set(None)  # Clear canonical ID

        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")

        # Should fail because no cache key can be generated without canonical_id
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.data)

    def test_subscribe_extracts_namespace_simple_equality(self):
        """Test that namespace is correctly extracted for simple equality filters."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"name": "TestA", "value": 10}
                    }
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        self.assertEqual(subscription.namespace, {"name": "TestA", "value": 10})

    def test_subscribe_extracts_namespace_in_lookup(self):
        """Test that namespace correctly extracts __in lookups."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"name__in": ["TestA", "TestB"]}
                    }
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        self.assertEqual(subscription.namespace, {"name__in": ["TestA", "TestB"]})

    def test_subscribe_excludes_unsupported_lookups(self):
        """Test that namespace excludes unsupported lookups like __gte."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {
                            "name": "TestA",
                            "value__gte": 10,
                            "id__lt": 100
                        }
                    }
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        # Should only include simple equality, not __gte or __lt
        self.assertEqual(subscription.namespace, {"name": "TestA"})

    def test_subscribe_empty_namespace_no_filter(self):
        """Test that namespace is empty dict when no filter is present."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        self.assertEqual(subscription.namespace, {})

    def test_subscribe_mixed_supported_unsupported_filters(self):
        """Test namespace extraction with mix of supported and unsupported filters."""
        self.client.force_authenticate(user=self.user)
        url = reverse("statezero:subscribe", args=["django_app.DummyModel"])

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {
                            "related_id": 5,
                            "name__in": ["TestA", "TestB"],
                            "value__gte": 10,
                            "name__contains": "test"
                        }
                    }
                }
            }
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)

        subscription = QuerySubscription.objects.get(id=response.data["subscription_id"])
        # Should only include equality and __in
        self.assertEqual(subscription.namespace, {
            "related_id": 5,
            "name__in": ["TestA", "TestB"]
        })

    def test_subscribe_populates_last_result_from_cache(self):
        """Test that when creating a subscription, last_result is populated from cache if available."""
        from tests.django_app.models import DummyModel
        import json

        # Create some test data
        obj1 = DummyModel.objects.create(name="CachedA", value=100)
        obj2 = DummyModel.objects.create(name="CachedB", value=200)

        self.client.force_authenticate(user=self.user)

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                }
            }
        }

        # First, execute the query via ModelView to populate cache
        model_view_url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        model_response = self.client.post(model_view_url, data=payload, format="json")
        self.assertEqual(model_response.status_code, 200)
        self.assertIn("data", model_response.data)

        # Now subscribe to the same query
        subscribe_url = reverse("statezero:subscribe", args=["django_app.DummyModel"])
        subscribe_response = self.client.post(subscribe_url, data=payload, format="json")
        self.assertEqual(subscribe_response.status_code, 200)
        self.assertTrue(subscribe_response.data["created"])

        # Verify that last_result was populated from cache
        subscription = QuerySubscription.objects.get(id=subscribe_response.data["subscription_id"])
        self.assertIsNotNone(subscription.last_result)

        # Compare by JSON serializing both sides to ensure exact match
        # This handles any int vs string key differences
        expected_json = json.dumps(model_response.data, sort_keys=True)
        actual_json = json.dumps(subscription.last_result, sort_keys=True)
        self.assertEqual(actual_json, expected_json)

        # Verify pk_index was populated
        self.assertIsNotNone(subscription.pk_index)
        self.assertIn("django_app.dummymodel", subscription.pk_index)
        # Should have 2 PKs
        pk_list = subscription.pk_index["django_app.dummymodel"]
        self.assertEqual(len(pk_list), 2)

        # Verify exact type preservation - should match what's in included dict
        included = model_response.data["data"]["included"]["django_app.dummymodel"]
        included_keys = list(included.keys())

        # pk_list should have exact same keys (same types)
        self.assertEqual(set(pk_list), set(included_keys))

        # Clean up
        obj1.delete()
        obj2.delete()

    def test_subscribe_no_last_result_when_cache_empty(self):
        """Test that last_result is None when creating a subscription with no cached data."""
        self.client.force_authenticate(user=self.user)

        payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {
                        "type": "filter",
                        "conditions": {"name": "NonExistentFilter"}
                    }
                }
            }
        }

        # Subscribe without running the query first (no cache)
        subscribe_url = reverse("statezero:subscribe", args=["django_app.DummyModel"])
        subscribe_response = self.client.post(subscribe_url, data=payload, format="json")
        self.assertEqual(subscribe_response.status_code, 200)
        self.assertTrue(subscribe_response.data["created"])

        # Verify that last_result is None
        subscription = QuerySubscription.objects.get(id=subscribe_response.data["subscription_id"])
        self.assertIsNone(subscription.last_result)
