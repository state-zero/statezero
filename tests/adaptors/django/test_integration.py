import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from .denormalize import denormalize
from tests.django_app.models import (ComprehensiveModel, DeepModelLevel1,
                                     DeepModelLevel2, DeepModelLevel3,
                                     DummyModel, DummyRelatedModel)


class ORMBridgeE2ETest(APITestCase):
    def setUp(self):
        # Create and log in a test user.
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create a DummyRelatedModel instance.
        self.related_dummy = DummyRelatedModel.objects.create(name="Related1")

        # Create the first related instance
        self.related_dummy_1 = DummyRelatedModel.objects.create(name="ValidRelated")
        # Create the second related instance
        self.related_dummy_2 = DummyRelatedModel.objects.create(name="NewRelated")

        # Create a DummyModel instance.
        self.dummy = DummyModel.objects.create(
            name="TestDummy", value=100, related=self.related_dummy
        )

        # Create deep nested model instances.
        self.deep_level3 = DeepModelLevel3.objects.create(name="Deep3")
        self.deep_level2 = DeepModelLevel2.objects.create(
            name="Deep2", level3=self.deep_level3
        )
        self.deep_level1 = DeepModelLevel1.objects.create(
            name="Deep1", level2=self.deep_level2
        )

        # Create a ComprehensiveModel instance that points to DeepModelLevel1.
        self.comprehensive = ComprehensiveModel.objects.create(
            char_field="TestChar",
            text_field="This is a test text",
            int_field=42,
            bool_field=True,
            datetime_field=timezone.now(),
            decimal_field=Decimal("123.45"),
            json_field={"key": "value"},
            money_field=Decimal("99.99"),
            related=self.deep_level1,
        )

        # Add the DummyModel instance to the many-to-many field on DeepModelLevel1.
        self.deep_level1.comprehensive_models.add(self.comprehensive)

    def test_update_instance_dummy_model(self):
        """Test that the instance-based update operation correctly modifies the database."""
        # Create a dummy model to update.
        initial_payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "UpdateTestModel",
                        "value": 100,
                        "related": self.related_dummy.id,
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        create_response = self.client.post(url, data=initial_payload, format="json")
        self.assertEqual(create_response.status_code, 200)

        # Get the ID of the created model.
        created_instance = denormalize((create_response.data.get("data", {})))
        instance_id = created_instance.get("id")
        self.assertIsNotNone(instance_id)

        # Verify initial state in the database.
        db_instance = DummyModel.objects.get(id=instance_id)
        self.assertEqual(db_instance.value, 100)

        # Now update the value using the instance-based update operation.
        update_payload = {
            "ast": {
                "query": {
                    "type": "update_instance",  # use instance-based update
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                    "data": {"value": 200},
                }
            }
        }

        update_response = self.client.post(url, data=update_payload, format="json")

        self.assertEqual(update_response.status_code, 200)
        metadata = update_response.data.get("metadata", {})
        self.assertTrue(metadata.get("updated", False))

        # Verify the database was actually updated.
        updated_db_instance = DummyModel.objects.get(id=instance_id)
        self.assertEqual(updated_db_instance.value, 200)

        # Issue a GET request to verify the API returns the updated value.
        get_payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                }
            }
        }
        get_response = self.client.post(url, data=get_payload, format="json")

        get_data = denormalize(get_response.data.get("data", {}))
        self.assertEqual(get_data.get("value"), 200)

    def test_update_instance_dummy_model_full_payload(self):
        """Test that an update with a full payload (including id and unchanged foreign key)
        correctly updates non-foreign-key fields.
        This simulates the frontend behavior of re-sending the complete serialized instance.
        """
        # Create a dummy model to update.
        initial_payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "FullPayloadUpdateTest",
                        "value": 100,
                        "related": self.related_dummy.id,
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        create_response = self.client.post(url, data=initial_payload, format="json")
        self.assertEqual(create_response.status_code, 200)
        created_instance = denormalize(create_response.data.get("data", {}))
        instance_id = created_instance.get("id")
        self.assertIsNotNone(instance_id)

        # Verify initial state.
        db_instance = DummyModel.objects.get(id=instance_id)
        self.assertEqual(db_instance.value, 100)

        # Prepare a full payload update including all fields as the frontend would send.
        full_payload_update = {
            "ast": {
                "query": {
                    "type": "update_instance",
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                    "data": {
                        "id": instance_id,  # re-sending the id
                        "name": "FullPayloadUpdateTest",  # unchanged
                        "value": 200,  # updated value
                        "related": self.related_dummy.id,  # unchanged foreign key
                    },
                }
            }
        }
        update_response = self.client.post(url, data=full_payload_update, format="json")
        self.assertEqual(update_response.status_code, 200)
        metadata = update_response.data.get("metadata", {})
        self.assertTrue(metadata.get("updated", False))

        # Verify the database was actually updated.
        updated_db_instance = DummyModel.objects.get(id=instance_id)
        self.assertEqual(updated_db_instance.value, 200)

        # Verify via a GET request that the API returns the updated value.
        get_payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                }
            }
        }
        get_response = self.client.post(url, data=get_payload, format="json")
        get_data = denormalize(get_response.data.get("data", {}))
        self.assertEqual(get_data.get("value"), 200)

    def test_delete_instance_dummy_model(self):
        """Test that the instance-based delete operation correctly removes the model from the database."""
        # Create a dummy model to delete.
        initial_payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "DeleteTestModel",
                        "value": 300,
                        "related": self.related_dummy.id,
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        create_response = self.client.post(url, data=initial_payload, format="json")
        self.assertEqual(create_response.status_code, 200)

        # Get the ID of the created model.
        created_instance = denormalize(create_response.data.get("data", {}))
        instance_id = created_instance.get("id")
        self.assertIsNotNone(instance_id)

        # Verify initial state in the database.
        db_instance = DummyModel.objects.get(id=instance_id)
        self.assertEqual(db_instance.value, 300)

        # Now delete the instance using the instance-based delete operation.
        delete_payload = {
            "ast": {
                "query": {
                    "type": "delete_instance",  # use instance-based delete
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                }
            }
        }

        delete_response = self.client.post(url, data=delete_payload, format="json")

        self.assertEqual(delete_response.status_code, 200)
        metadata = delete_response.data.get("metadata", {})
        self.assertTrue(metadata.get("deleted", False))

        # Verify that the instance has been deleted from the database.
        with self.assertRaises(DummyModel.DoesNotExist):
            DummyModel.objects.get(id=instance_id)

    def test_schema_endpoint_for_dummy_model(self):
        url = reverse("statezero:schema_view", args=["django_app.DummyModel"])
        response = self.client.generic(
            "GET", url, data="{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.data
        # Expect top-level keys from the new schema format.
        self.assertIn("model_name", data)
        self.assertIn("title", data)
        self.assertIn("class_name", data)
        self.assertIn("plural_title", data)
        self.assertIn("primary_key_field", data)
        self.assertIn("properties", data)
        self.assertIn("relationships", data)
        # Verify that at least one property includes expected metadata (e.g. "name")
        properties = data["properties"]
        self.assertIn("name", properties)
        self.assertIn("title", properties["name"])
        self.assertIn("type", properties["name"])

    def test_get_dummy_model(self):
        # Send a GET with an explicit AST for a read operation.
        payload = {"ast": {"query": {"type": "read"}}}
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        # Expect a dict with "data" and "metadata".
        data = denormalize(response.data.get("data", None))
        self.assertIsNotNone(data)
        self.assertTrue(any("id" in item for item in data))

    def test_create_dummy_model(self):
        # Wrap the create payload in an AST structure.
        payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "NewDummy",
                        "value": 200,
                        "related": self.related_dummy.id,
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(DummyModel.objects.filter(name="NewDummy").exists())

    def test_schema_endpoint_for_comprehensive_model(self):
        url = reverse("statezero:schema_view", args=["django_app.ComprehensiveModel"])
        response = self.client.generic(
            "GET", url, data="{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.data
        # Validate that the new schema format is returned.
        self.assertIn("model_name", data)
        self.assertIn("title", data)
        self.assertIn("class_name", data)
        self.assertIn("plural_title", data)
        self.assertIn("primary_key_field", data)
        self.assertIn("properties", data)
        self.assertIn("relationships", data)
        # Check that properties include expected fields.
        properties = data["properties"]
        self.assertIn("char_field", properties)
        self.assertIn("decimal_field", properties)
        self.assertIn("json_field", properties)

    def test_events_auth(self):
        url = reverse("statezero:events_auth")
        payload = {"channel_name": "private-django_app", "socket_id": "123.456"}
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("auth", response.data)
        self.assertEqual(1, len(response.data))

    def test_deep_model_schema(self):
        url = reverse("statezero:schema_view", args=["django_app.DeepModelLevel1"])
        response = self.client.generic(
            "GET", url, data="{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.data
        # Validate that the new schema format is returned.
        self.assertIn("model_name", data)
        self.assertIn("properties", data)
        self.assertIn("relationships", data)
        # For DeepModelLevel1, check that the properties include expected keys.
        properties = data["properties"]
        self.assertTrue("name" in properties or "repr" in properties)
        self.assertIn("level2", properties)
        self.assertIn("comprehensive_models", properties)

    def test_deep_model_get(self):
        # Send a GET with an explicit AST for a read operation.
        payload = {"ast": {"query": {"type": "read"}}}
        url = reverse("statezero:model_view", args=["django_app.DeepModelLevel1"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = denormalize(response.data.get("data", None))
        self.assertIsNotNone(data)
        if isinstance(data, list):
            deep_instance = data[0]
        else:
            deep_instance = data

        self.assertIn("name", deep_instance)
        self.assertIn("level2", deep_instance)
        level2_repr = deep_instance["level2"]
        self.assertTrue(isinstance(level2_repr, dict))
        self.assertIn("repr", level2_repr)

        self.assertIn("comprehensive_models", deep_instance)
        comprehensive_list = deep_instance["comprehensive_models"]
        self.assertTrue(isinstance(comprehensive_list, list))
        if comprehensive_list:
            self.assertIsInstance(comprehensive_list[0], dict)
            self.assertIn("id", comprehensive_list[0])

    def test_update_related_field_direct_api_call(self):
        """Test updating a related field directly using the API call."""
        # Create the main instance with the first related object
        initial_payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "RelatedUpdateTest",
                        "value": 200,
                        "related": self.related_dummy_1.id,
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        create_response = self.client.post(url, data=initial_payload, format="json")
        self.assertEqual(create_response.status_code, 200)

        # Get the ID of the created model
        created_instance = denormalize(create_response.data.get("data", {}))
        instance_id = created_instance.get("id")
        self.assertIsNotNone(instance_id)

        # Verify initial related field
        db_instance = DummyModel.objects.get(id=instance_id)
        self.assertEqual(db_instance.related.id, self.related_dummy_1.id)

        # Print the database state for debugging
        print(
            f"Initial database state: Instance {instance_id} has related_id={db_instance.related.id}"
        )

        # Now update the related field to the second related object
        update_payload = {
            "ast": {
                "query": {
                    "type": "update_instance",
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                    "data": {
                        "id": instance_id,
                        "name": "RelatedUpdateTest",
                        "value": 200,
                        "related": self.related_dummy_2.id,
                    },
                }
            }
        }

        # Print the update payload for debugging
        print(f"Sending update payload: {json.dumps(update_payload)}")

        update_response = self.client.post(url, data=update_payload, format="json")
        self.assertEqual(update_response.status_code, 200)

        # Print the update response for debugging
        print(f"Update response: {json.dumps(update_response.data)}")

        # Verify the database was actually updated
        updated_db_instance = DummyModel.objects.get(id=instance_id)
        print(
            f"Database after update: Instance {instance_id} has related_id={updated_db_instance.related.id}"
        )

        # Check that the related field was updated in the database
        self.assertEqual(updated_db_instance.related.id, self.related_dummy_2.id)

        # Now make a GET request to verify the API returns the updated related ID
        get_payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                }
            }
        }
        get_response = self.client.post(url, data=get_payload, format="json")

        # Print the GET response for debugging
        print(f"GET response after update: {json.dumps(denormalize(get_response.data))}")

        get_data = denormalize(get_response.data.get("data", {}))
        related_id_in_response = get_data.get("related", {}).get("id")
        self.assertEqual(related_id_in_response, self.related_dummy_2.id)

    def test_update_related_field_only(self):
        """Test updating only the related field (without sending other fields)."""
        # Create the main instance with the first related object
        initial_payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "RelatedOnlyUpdateTest",
                        "value": 200,
                        "related": self.related_dummy_1.id,
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        create_response = self.client.post(url, data=initial_payload, format="json")
        self.assertEqual(create_response.status_code, 200)

        # Get the ID of the created model
        created_instance = denormalize(create_response.data.get("data", {}))
        instance_id = created_instance.get("id")
        self.assertIsNotNone(instance_id)

        # Now update ONLY the related field
        update_payload = {
            "ast": {
                "query": {
                    "type": "update_instance",
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                    "data": {"related": self.related_dummy_2.id},
                }
            }
        }

        print(f"Sending related-only update payload: {json.dumps(update_payload)}")

        update_response = self.client.post(url, data=update_payload, format="json")
        self.assertEqual(update_response.status_code, 200)

        print(f"Related-only update response: {json.dumps(update_response.data)}")

        # Verify the database was actually updated
        updated_db_instance = DummyModel.objects.get(id=instance_id)
        print(
            f"Database after related-only update: Instance {instance_id} has related_id={updated_db_instance.related.id}"
        )

        # This is the key assertion - it should be updated to the new related ID
        self.assertEqual(updated_db_instance.related.id, self.related_dummy_2.id)

        # Verify via a GET request
        get_payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                }
            }
        }
        get_response = self.client.post(url, data=get_payload, format="json")
        get_data = denormalize(get_response.data.get("data", {}))
        related_id_in_response = get_data.get("related", {}).get("id")
        self.assertEqual(related_id_in_response, self.related_dummy_2.id)

    def test_instance_level_delete_with_cache_check(self):
        """
        Test that deleting an instance directly triggers cache invalidation.
        This simulates the frontend behavior where instance.delete() is called
        and then a subsequent query checks if the instance still exists.
        """
        # Create a dummy model to delete
        initial_payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "InstanceDeleteCacheTest",
                        "value": 500,
                        "related": self.related_dummy.id,
                    },
                }
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        create_response = self.client.post(url, data=initial_payload, format="json")
        self.assertEqual(create_response.status_code, 200)

        # Get the ID of the created model
        created_instance = denormalize(create_response.data.get("data", {}))
        instance_id = created_instance.get("id")
        self.assertIsNotNone(instance_id)

        # First verify the instance exists using a filter query (this will cache the result)
        check_exists_payload = {
            "ast": {
                "query": {
                    "type": "read",
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                }
            }
        }
        exists_response = self.client.post(
            url, data=check_exists_payload, format="json"
        )
        self.assertEqual(exists_response.status_code, 200)
        exists_data = denormalize(exists_response.data.get("data", []))
        self.assertTrue(len(exists_data) > 0, "Instance should exist before deletion")

        # Now delete the instance using instance-level delete
        delete_payload = {
            "ast": {
                "query": {
                    "type": "delete_instance",
                    "filter": {"type": "filter", "conditions": {"id": instance_id}},
                }
            }
        }

        delete_response = self.client.post(url, data=delete_payload, format="json")
        self.assertEqual(delete_response.status_code, 200)

        # Capture the delete response data to verify it matches the Django tuple format
        delete_data = delete_response.data.get("data", 0)
        self.assertEqual(delete_data, 1, "Delete response should return count of 1")

        # Immediately check if the instance still exists - this tests cache invalidation
        check_after_delete_response = self.client.post(
            url, data=check_exists_payload, format="json"
        )
        after_delete_data = denormalize(check_after_delete_response.data.get("data", []))
        self.assertEqual(
            len(after_delete_data),
            0,
            "Instance should not exist after deletion (cache should be invalidated)",
        )

        # Verify that the instance has been deleted from the database
        with self.assertRaises(DummyModel.DoesNotExist):
            DummyModel.objects.get(id=instance_id)

    def test_get_or_create_method(self):
        """Test that the getOrCreate method works correctly for both existing and new instances."""

        # Use a unique name for this test to avoid conflicts
        import time

        unique_prefix = f"TestGetOrCreate_{int(time.time())}"

        # First, create a related model for FK relationships
        related = DummyRelatedModel.objects.create(name=f"{unique_prefix}_ValidRelated")

        # Create an instance first that we can later retrieve
        existing = DummyModel.objects.create(
            name=f"{unique_prefix}_ExistingTest", value=10, related=related
        )

        # 1. Test getting an existing instance
        get_existing_payload = {
            "ast": {
                "query": {
                    "type": "get_or_create",
                    "lookup": {"name": f"{unique_prefix}_ExistingTest"},
                    "defaults": {},
                }
            }
        }

        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        get_existing_response = self.client.post(
            url, data=get_existing_payload, format="json"
        )

        self.assertEqual(get_existing_response.status_code, 200)
        metadata = get_existing_response.data.get("metadata", {})
        self.assertFalse(
            metadata.get("created", True), "Should not create a new instance"
        )
        data = denormalize(get_existing_response.data.get("data", {}))
        self.assertEqual(
            data.get("id"), existing.id, "Should retrieve the existing instance"
        )

        # 2. Test creating a new instance
        new_name = f"{unique_prefix}_NewGetOrCreateTest"
        get_new_payload = {
            "ast": {
                "query": {
                    "type": "get_or_create",
                    "lookup": {"name": new_name},
                    "defaults": {"value": 20, "related": related.id},
                }
            }
        }

        # Verify no instance exists yet with this name
        self.assertFalse(DummyModel.objects.filter(name=new_name).exists())
        get_new_response = self.client.post(url, data=get_new_payload, format="json")
        self.assertEqual(get_new_response.status_code, 200)
        new_metadata = get_new_response.data.get("metadata", {})
        self.assertTrue(
            new_metadata.get("created", False), "Should create a new instance"
        )
        new_data = denormalize(get_new_response.data.get("data", {}))
        self.assertEqual(
            new_data.get("name"), new_name, "Should set the name correctly"
        )
        self.assertEqual(new_data.get("value"), 20, "Should use the default value")

        # Verify the instance was created in the database
        self.assertTrue(DummyModel.objects.filter(name=new_name).exists())

        # 3. Test get_or_create with special characters in the name
        special_name = f"{unique_prefix}_Test@#$%^&*()"
        special_payload = {
            "ast": {
                "query": {
                    "type": "get_or_create",
                    "lookup": {"name": special_name},
                    "defaults": {"value": 30, "related": related.id},
                }
            }
        }

        special_response = self.client.post(url, data=special_payload, format="json")
        self.assertEqual(special_response.status_code, 200)
        special_data = denormalize(special_response.data.get("data", {}))
        self.assertEqual(
            special_data.get("name"), special_name, "Should handle special characters"
        )

        # 4. Test creating with no defaults (should fail if 'related' is required)
        missing_required_payload = {
            "ast": {
                "query": {
                    "type": "get_or_create",
                    "lookup": {"value": 50},
                    "defaults": {},  # Missing required fields
                }
            }
        }

        missing_response = self.client.post(
            url, data=missing_required_payload, format="json"
        )
        # This should return a validation error
        self.assertEqual(missing_response.status_code, 400)

        # 5. Test with minimal valid defaults
        minimal_name = f"{unique_prefix}_MinimalValid"
        minimal_payload = {
            "ast": {
                "query": {
                    "type": "get_or_create",
                    "lookup": {"name": minimal_name},
                    "defaults": {
                        "related": related.id  # Only providing required field
                    },
                }
            }
        }

        minimal_response = self.client.post(url, data=minimal_payload, format="json")
        self.assertEqual(minimal_response.status_code, 200)
        minimal_data = denormalize(minimal_response.data.get("data", {}))
        self.assertEqual(minimal_data.get("name"), minimal_name)

        # 6. Test that defaults aren't used when retrieving existing
        existing_with_defaults_payload = {
            "ast": {
                "query": {
                    "type": "get_or_create",
                    "lookup": {"name": f"{unique_prefix}_ExistingTest"},
                    "defaults": {
                        "value": 999  # This should be ignored when getting existing
                    },
                }
            }
        }

        existing_defaults_response = self.client.post(
            url, data=existing_with_defaults_payload, format="json"
        )
        self.assertEqual(existing_defaults_response.status_code, 200)
        existing_defaults_data = denormalize(existing_defaults_response.data.get("data", {}))
        # Verify original value is preserved, not the default
        self.assertEqual(existing_defaults_data.get("value"), 10)

        # 7. Test that multiple matching objects raise an error
        # Create duplicates manually
        DummyModel.objects.create(
            name=f"{unique_prefix}_DuplicateTest", value=10, related=related
        )
        DummyModel.objects.create(
            name=f"{unique_prefix}_DuplicateTest", value=20, related=related
        )

        duplicate_payload = {
            "ast": {
                "query": {
                    "type": "get_or_create",
                    "lookup": {"name": f"{unique_prefix}_DuplicateTest"},
                    "defaults": {},
                }
            }
        }

        # The request should now raise an error. Depending on your error handling,
        # you might receive a 400 response with error details.
        duplicate_response = self.client.post(
            url, data=duplicate_payload, format="json"
        )
        self.assertEqual(duplicate_response.status_code, 400)
        # Optionally, check for the error detail indicating multiple objects were returned
        error_detail = duplicate_response.data.get("detail", {})
        self.assertEqual(error_detail.get("code"), "multiple_objects_returned")

    def test_update_or_create_method(self):
        """Test that the update_or_create method works correctly for both updating existing and creating new instances."""
        import json
        import time

        unique_prefix = f"TestUpdateOrCreate_{int(time.time())}"

        # Create a related model for FK relationships.
        related = DummyRelatedModel.objects.create(name=f"{unique_prefix}_ValidRelated")

        # Create an existing instance that we will later update.
        existing = DummyModel.objects.create(
            name=f"{unique_prefix}_ExistingTest", value=10, related=related
        )

        url = reverse("statezero:model_view", args=["django_app.DummyModel"])

        # 1. Test updating an existing instance.
        update_existing_payload = {
            "ast": {
                "query": {
                    "type": "update_or_create",
                    "lookup": {"name": f"{unique_prefix}_ExistingTest"},
                    "defaults": {"value": 50},
                }
            }
        }
        update_existing_response = self.client.post(
            url, data=update_existing_payload, format="json"
        )

        self.assertEqual(update_existing_response.status_code, 200)
        updated_metadata = update_existing_response.data.get("metadata", {})
        self.assertFalse(
            updated_metadata.get("created", True),
            "Should update the existing instance, not create a new one",
        )
        updated_data = denormalize(update_existing_response.data.get("data", {}))
        self.assertEqual(
            updated_data.get("id"), existing.id, "Should update the existing instance"
        )
        self.assertEqual(
            updated_data.get("value"), 50, "The value should be updated to 50"
        )

        # 2. Test creating a new instance.
        new_name = f"{unique_prefix}_NewTest"
        update_new_payload = {
            "ast": {
                "query": {
                    "type": "update_or_create",
                    "lookup": {"name": new_name},
                    "defaults": {"value": 20, "related": related.id},
                }
            }
        }

        # Verify no instance exists yet with this name.
        self.assertFalse(DummyModel.objects.filter(name=new_name).exists())

        update_new_response = self.client.post(
            url, data=update_new_payload, format="json"
        )

        self.assertEqual(update_new_response.status_code, 200)
        new_metadata = update_new_response.data.get("metadata", {})
        self.assertTrue(
            new_metadata.get("created", False),
            "Should create a new instance when none exists",
        )
        new_data = denormalize(update_new_response.data.get("data", {}))
        self.assertEqual(
            new_data.get("name"),
            new_name,
            "The new instance should have the correct name",
        )
        self.assertEqual(
            new_data.get("value"), 20, "The new instance should have the provided value"
        )

        # Verify the new instance was created in the database.
        self.assertTrue(DummyModel.objects.filter(name=new_name).exists())

        # 3. Test update_or_create with special characters in the name.
        special_name = f"{unique_prefix}_Special@#$%^&*()"
        special_payload = {
            "ast": {
                "query": {
                    "type": "update_or_create",
                    "lookup": {"name": special_name},
                    "defaults": {"value": 30, "related": related.id},
                }
            }
        }
        special_response = self.client.post(url, data=special_payload, format="json")
        self.assertEqual(special_response.status_code, 200)
        special_data = denormalize(special_response.data.get("data", {}))
        self.assertEqual(
            special_data.get("name"),
            special_name,
            "Should handle special characters in the name",
        )

        # 4. Test that multiple matching objects raise an error.
        # Create duplicates manually.
        DummyModel.objects.create(
            name=f"{unique_prefix}_DuplicateTest", value=10, related=related
        )
        DummyModel.objects.create(
            name=f"{unique_prefix}_DuplicateTest", value=20, related=related
        )

        duplicate_payload = {
            "ast": {
                "query": {
                    "type": "update_or_create",
                    "lookup": {"name": f"{unique_prefix}_DuplicateTest"},
                    "defaults": {},
                }
            }
        }

        duplicate_response = self.client.post(
            url, data=duplicate_payload, format="json"
        )
        self.assertEqual(duplicate_response.status_code, 400)
        error_detail = duplicate_response.data.get("detail", {})
        # Adjust the assertion based on your error response structure.
        self.assertEqual(error_detail.get("code"), "multiple_objects_returned")

    def test_field_selection_basic(self):
        """Test basic field selection with simple fields."""
        # Create a payload requesting only specific fields
        payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.comprehensive.id},
                    },
                },
                "serializerOptions": {
                    "fields": [
                        "id",
                        "char_field",
                        "int_field",
                    ]  # Only select these fields
                },
            }
        }

        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = denormalize(response.data.get("data", {}))

        # Verify only requested fields are present
        self.assertIn("id", data)
        self.assertIn("char_field", data)
        self.assertIn("int_field", data)

        # Verify other fields are not present
        self.assertNotIn("text_field", data)
        self.assertNotIn("bool_field", data)
        self.assertNotIn("decimal_field", data)
        self.assertNotIn("json_field", data)

        # Verify values are correct
        self.assertEqual(data["id"], self.comprehensive.id)
        self.assertEqual(data["char_field"], "TestChar")
        self.assertEqual(data["int_field"], 42)

    def test_field_selection_with_related(self):
        """Test field selection including a related field."""
        # Create a payload that includes a related field
        payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.comprehensive.id},
                    },
                },
                "serializerOptions": {
                    "fields": ["id", "char_field", "related"]  # Select a relation field
                },
            }
        }

        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = denormalize(response.data.get("data", {}))

        # Verify only requested fields are present
        self.assertIn("id", data)
        self.assertIn("char_field", data)
        self.assertIn("related", data)

        # Verify other fields are not present
        self.assertNotIn("int_field", data)
        self.assertNotIn("text_field", data)

        # Verify related field is returned
        self.assertIsInstance(data["related"], dict)
        self.assertIn("id", data["related"])
        self.assertEqual(data["related"]["id"], self.deep_level1.id)

    def test_field_selection_nested_related(self):
        """Test field selection with nested related fields using the format 'related__name'."""
        # Create a payload with nested field selection
        payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.comprehensive.id},
                    },
                },
                "serializerOptions": {
                    "fields": ["id", "related__name", "related__level2__name"]
                },
            }
        }

        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data = denormalize(response.data.get("data", {}))

        # Verify only requested fields are present
        self.assertIn("id", data)
        self.assertIn("related", data)

        # Verify related object has only the requested fields
        self.assertIn("name", data["related"])
        self.assertEqual(data["related"]["name"], "Deep1")

        # Verify nested relation is included
        self.assertIn("level2", data["related"])
        self.assertIn("name", data["related"]["level2"])
        self.assertEqual(data["related"]["level2"]["name"], "Deep2")

        # Verify other fields of related aren't included
        if isinstance(data["related"], dict) and "level2" in data["related"]:
            level2 = data["related"]["level2"]
            # level3 field should not be included since we only requested level2's name
            self.assertNotIn("level3", level2)

    def test_field_selection_list_endpoint(self):
        """Test field selection works on list endpoints."""
        # Create a payload for list endpoint with field selection
        payload = {
            "ast": {
                "query": {
                    "type": "read",
                },
                "serializerOptions": {
                    "fields": ["id", "name"]  # Only select ID and name
                },
            }
        }

        url = reverse("statezero:model_view", args=["django_app.DummyModel"])
        response = self.client.post(url, data=payload, format="json")

        self.assertEqual(response.status_code, 200)
        data_list = denormalize(response.data.get("data", []))

        # Ensure we got some results
        self.assertTrue(len(data_list) > 0)

        # Check first item in the list
        first_item = data_list[0]

        # Verify only requested fields are present
        self.assertIn("id", first_item)
        self.assertIn("name", first_item)

        # Verify other fields are not present
        self.assertNotIn("value", first_item)
        self.assertNotIn("related", first_item)

    def test_field_selection_empty(self):
        """Test behavior when an empty fields list is provided."""
        # Create a payload with empty fields list
        payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.comprehensive.id},
                    },
                },
                "serializerOptions": {"fields": []},  # Empty field selection
            }
        }

        url = reverse("statezero:model_view", args=["django_app.ComprehensiveModel"])
        response = self.client.post(url, data=payload, format="json")

        # The behavior might vary - either return all fields or return an error
        # Let's assume it should return all fields for an empty list
        self.assertEqual(response.status_code, 200)
        data = denormalize(response.data.get("data", {}))

        # Verify that more than just id is returned (default behavior)
        self.assertIn("id", data)
        self.assertIn("char_field", data)

    def test_deep_model_default_depth_behavior(self):
        """
        Test that with a default depth of 1 and no explicit deeper field request,
        only the first level of related fields (i.e. level2) is fully expanded.
        The nested level3 within level2 should remain minimal (or be absent).
        """
        payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {"type": "filter", "conditions": {"id": self.deep_level1.id}},
                },
                "serializerOptions": {
                    "fields": ["id", "name", "level2", "level2__name"]
                },
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DeepModelLevel1"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = denormalize(response.data.get("data", {}))

        # Verify root-level fields.
        self.assertEqual(data.get("id"), self.deep_level1.id)
        self.assertEqual(data.get("name"), "Deep1")

        # Check that level2 is expanded and includes its own 'name'
        self.assertIn("level2", data)
        self.assertIsInstance(data["level2"], dict)
        self.assertIn("name", data["level2"])
        self.assertEqual(data["level2"]["name"], "Deep2")

        # Without an explicit request, level2's nested level3 should not be fully expanded.
        if "level3" in data["level2"]:
            # Minimal representation should not include the 'name' field.
            self.assertNotIn("name", data["level2"]["level3"])
        else:
            # Or it might be None.
            self.assertIsNone(data["level2"].get("level3"))

    def test_deep_model_explicit_deep_field_request(self):
        """
        Test that explicitly requesting a nested field (e.g. 'level2__level3__name')
        forces the serializer to expand that nested field even when the default depth is 0.
        """
        payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {"type": "filter", "conditions": {"id": self.deep_level1.id}},
                },
                "serializerOptions": {
                    "fields": ["id", "name", "level2__name", "level2__level3__name"]
                },
            }
        }
        url = reverse("statezero:model_view", args=["django_app.DeepModelLevel1"])
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 200)
        data = denormalize(response.data.get("data", {}))

        # Verify root-level fields.
        self.assertEqual(data.get("id"), self.deep_level1.id)
        self.assertEqual(data.get("name"), "Deep1")

        # Verify that level2 is expanded and includes its own 'name'
        self.assertIn("level2", data)
        self.assertIsInstance(data["level2"], dict)
        self.assertIn("name", data["level2"])
        self.assertEqual(data["level2"]["name"], "Deep2")

        # The explicit request for 'level2__level3__name' forces level3 to be expanded.
        self.assertIn("level3", data["level2"])
        self.assertIsInstance(data["level2"]["level3"], dict)
        self.assertIn("name", data["level2"]["level3"])
        self.assertEqual(data["level2"]["level3"]["name"], "Deep3")