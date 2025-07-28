import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from tests.django_app.models import (
    ComprehensiveModel, DeepModelLevel1, DeepModelLevel2, DeepModelLevel3,
    DummyModel, DummyRelatedModel
)


class BatchEndpointTest(APITestCase):
    """
    Test the batch endpoint that processes multiple operations atomically.
    """
    
    def setUp(self):
        # Create and log in a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create test data
        self.related_dummy = DummyRelatedModel.objects.create(name="Related1")
        self.dummy = DummyModel.objects.create(
            name="TestDummy", value=100, related=self.related_dummy
        )
        
        # Deep model setup for testing relationships
        self.deep_level3 = DeepModelLevel3.objects.create(name="Deep3")
        self.deep_level2 = DeepModelLevel2.objects.create(
            name="Deep2", level3=self.deep_level3
        )
        self.deep_level1 = DeepModelLevel1.objects.create(
            name="Deep1", level2=self.deep_level2
        )

        # Create a ComprehensiveModel instance
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
        
        # Endpoint URL
        self.batch_url = reverse("statezero:batch_view")

    def test_batch_success(self):
        """Test successful batch operations."""
        batch_payload = {
            "operations": [
                {
                    "model": "django_app.DummyModel",
                    "query": {
                        "type": "create",
                        "data": {
                            "name": "BatchModel1",
                            "value": 101,
                            "related": self.related_dummy.id
                        }
                    },
                    "id": "create_op_1"
                },
                {
                    "model": "django_app.DummyModel",
                    "query": {
                        "type": "create",
                        "data": {
                            "name": "BatchModel2",
                            "value": 102,
                            "related": self.related_dummy.id
                        }
                    },
                    "id": "create_op_2"
                }
            ]
        }
        
        response = self.client.post(self.batch_url, data=batch_payload, format="json")
        self.assertEqual(response.status_code, 200)
        
        # Check response structure
        self.assertIn("results", response.data)
        results = response.data["results"]
        self.assertEqual(len(results), 2)
        
        # Check that each operation has the expected structure
        for result in results:
            self.assertIn("id", result)
            self.assertIn("data", result)
            self.assertIn("status", result)
            self.assertEqual(result["status"], "success")
        
        # Verify both models were created in database
        self.assertTrue(DummyModel.objects.filter(name="BatchModel1").exists())
        self.assertTrue(DummyModel.objects.filter(name="BatchModel2").exists())
    
    def test_batch_failure_rollback(self):
        """Test that transaction rollback works when an operation fails."""
        batch_payload = {
            "operations": [
                {
                    "model": "django_app.DummyModel",
                    "query": {
                        "type": "create",
                        "data": {
                            "name": "ValidBatchModel",
                            "value": 201,
                            "related": self.related_dummy.id
                        }
                    },
                    "id": "valid_op"
                },
                {
                    "model": "django_app.DummyModel",
                    "query": {
                        "type": "create",
                        "data": {
                            "name": "InvalidBatchModel",
                            "value": "not_an_integer",  # Invalid data type for value field
                            "related": self.related_dummy.id
                        }
                    },
                    "id": "invalid_op"
                }
            ]
        }
        
        response = self.client.post(self.batch_url, data=batch_payload, format="json")
        self.assertEqual(response.status_code, 400)
        
        # Check error response structure
        self.assertIn("error", response.data)
        self.assertIn("transaction_failed", response.data)
        self.assertTrue(response.data["transaction_failed"])
        
        # Check failed operation details
        self.assertIn("failed_operation", response.data)
        failed_op = response.data["failed_operation"]
        self.assertEqual(failed_op["id"], "invalid_op")
        self.assertEqual(failed_op["index"], 1)
        
        # Verify rollback occurred and neither model was created
        self.assertFalse(DummyModel.objects.filter(name="ValidBatchModel").exists())
        self.assertFalse(DummyModel.objects.filter(name="InvalidBatchModel").exists())
    
    def test_batch_missing_model(self):
        """Test handling of missing model name."""
        batch_payload = {
            "operations": [
                {
                    "model": "",  # Missing model name
                    "query": {
                        "type": "create",
                        "data": {
                            "name": "MissingModelTest",
                            "value": 300,
                            "related": self.related_dummy.id
                        }
                    },
                    "id": "missing_model_op"
                }
            ]
        }
        
        response = self.client.post(self.batch_url, data=batch_payload, format="json")
        self.assertEqual(response.status_code, 400)
        
        # Check error response
        self.assertIn("error", response.data)
        self.assertEqual(response.data["error"], "Missing model name")
        
        # Check failed operation details
        self.assertIn("failed_operation", response.data)
        failed_op = response.data["failed_operation"]
        self.assertEqual(failed_op["id"], "missing_model_op")
        self.assertEqual(failed_op["index"], 0)
    
    def test_batch_multiple_operation_types(self):
        """Test batch processing with different operation types."""
        # Create a model to update and delete in the batch
        model_to_update = DummyModel.objects.create(
            name="UpdateMe", value=400, related=self.related_dummy
        )
        model_to_delete = DummyModel.objects.create(
            name="DeleteMe", value=500, related=self.related_dummy
        )
        
        batch_payload = {
            "operations": [
                {
                    "model": "django_app.DummyModel",
                    "query": {
                        "type": "create",
                        "data": {
                            "name": "BatchCreate",
                            "value": 600,
                            "related": self.related_dummy.id
                        }
                    },
                    "id": "create_op"
                },
                {
                    "model": "django_app.DummyModel",
                    "query": {
                        "type": "update_instance",
                        "filter": {"type": "filter", "conditions": {"id": model_to_update.id}},
                        "data": {"value": 450}
                    },
                    "id": "update_op"
                },
                {
                    "model": "django_app.DummyModel",
                    "query": {
                        "type": "delete_instance",
                        "filter": {"type": "filter", "conditions": {"id": model_to_delete.id}}
                    },
                    "id": "delete_op"
                },
                {
                    "model": "django_app.DummyModel",
                    "query": {
                        "type": "read",
                        "filter": {"type": "filter", "conditions": {"name": "TestDummy"}}
                    },
                    "id": "read_op"
                }
            ]
        }
        
        response = self.client.post(self.batch_url, data=batch_payload, format="json")
        self.assertEqual(response.status_code, 200)
        
        # Check that operations were successful
        results = response.data["results"]
        self.assertEqual(len(results), 4)
        
        # Check results by operation ID
        result_by_id = {r["id"]: r for r in results}
        
        # Verify create operation
        self.assertEqual(result_by_id["create_op"]["status"], "success")
        self.assertTrue(DummyModel.objects.filter(name="BatchCreate").exists())
        
        # Verify update operation
        self.assertEqual(result_by_id["update_op"]["status"], "success")
        updated_model = DummyModel.objects.get(id=model_to_update.id)
        self.assertEqual(updated_model.value, 450)
        
        # Verify delete operation
        self.assertEqual(result_by_id["delete_op"]["status"], "success")
        with self.assertRaises(DummyModel.DoesNotExist):
            DummyModel.objects.get(id=model_to_delete.id)
        
        # Verify read operation
        self.assertEqual(result_by_id["read_op"]["status"], "success")
        
        # The 'data' field of the read operation's result contains a dictionary
        read_result_dict = result_by_id["read_op"]["data"] 
        self.assertIsInstance(read_result_dict, dict) # Check it's a dictionary
        self.assertIn("data", read_result_dict)      # Check the nested 'data' key exists
        self.assertIn("metadata", read_result_dict)  # Check the 'metadata' key exists

        # Access the actual list of data items
        actual_read_data_list = read_result_dict["data"] 
        self.assertIsInstance(actual_read_data_list, list) # Now assert this is a list
        
        # Perform checks on the data within the list
        self.assertGreaterEqual(len(actual_read_data_list), 1) # Make sure there's at least one item
        self.assertEqual(actual_read_data_list[0]["name"], "TestDummy")
    
    def test_batch_empty_operations(self):
        """Test handling of empty operations list."""
        batch_payload = {
            "operations": []
        }
        
        response = self.client.post(self.batch_url, data=batch_payload, format="json")
        self.assertEqual(response.status_code, 400)
        
        # Check error response
        self.assertIn("error", response.data)
        self.assertEqual(response.data["error"], "No operations provided")
    
    def test_batch_invalid_model(self):
        """Test handling of non-existent model."""
        batch_payload = {
            "operations": [
                {
                    "model": "django_app.NonExistentModel",
                    "query": {
                        "type": "read"
                    },
                    "id": "invalid_model_op"
                }
            ]
        }
        
        response = self.client.post(self.batch_url, data=batch_payload, format="json")
        self.assertEqual(response.status_code, 400)
        
        # Check error response
        self.assertIn("error", response.data)
        self.assertIn("transaction_failed", response.data)
        
        # Check failed operation details
        self.assertIn("failed_operation", response.data)
        failed_op = response.data["failed_operation"]
        self.assertEqual(failed_op["id"], "invalid_model_op")
        self.assertEqual(failed_op["model"], "django_app.NonExistentModel")
    
    def test_batch_with_dependencies(self):
        """Test batch operations where later operations depend on results from earlier ones."""
        batch_payload = {
            "operations": [
                # First create a related model
                {
                    "model": "django_app.DummyRelatedModel",
                    "query": {
                        "type": "create",
                        "data": {
                            "name": "BatchRelatedModel"
                        }
                    },
                    "id": "create_related"
                },
                # Then create a model that uses the ID from the first operation
                # In practice, the frontend would need to extract and use this ID
                # This just tests that both creation operations happen in the transaction
                {
                    "model": "django_app.DummyModel",
                    "query": {
                        "type": "create",
                        "data": {
                            "name": "ModelWithDependency",
                            "value": 700,
                            "related": "PLACEHOLDER"  # We can't actually reference previous results in the test
                        }
                    },
                    "id": "create_dependent"
                }
            ]
        }
        
        response = self.client.post(self.batch_url, data=batch_payload, format="json")
        
        # Since we can't actually reference the ID from the first operation,
        # this will fail due to the PLACEHOLDER, but we can check that the first 
        # operation's model was created and then rolled back
        self.assertEqual(response.status_code, 400)
        
        # Verify that the transaction was rolled back
        self.assertFalse(DummyRelatedModel.objects.filter(name="BatchRelatedModel").exists())
        self.assertFalse(DummyModel.objects.filter(name="ModelWithDependency").exists())