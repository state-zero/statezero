import logging

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from modelsync.adaptors.django.config import config
from modelsync.adaptors.django.event_emitters import DjangoConsoleEventEmitter
from modelsync.core.context_storage import current_operation_id
from modelsync.core.types import ActionType
from tests.django_app.models import DummyModel, DummyRelatedModel


# A custom logging handler to capture log records.
class LogCaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class ModelSyncE2ETest(APITestCase):
    def setUp(self):
        # Create and log in a test user.
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create a DummyRelatedModel instance.
        self.related_dummy = DummyRelatedModel.objects.create(name="Related1")

        # Create a DummyModel instance.
        self.dummy = DummyModel.objects.create(
            name="TestDummy", value=100, related=self.related_dummy
        )

    def test_operation_id_emitted_on_create(self):
        # Set up log capturing on the emitter's logger.
        logger = logging.getLogger("modelsync.core.event_emitters")
        capture_handler = LogCaptureHandler()
        logger.addHandler(capture_handler)
        logger.setLevel(logging.INFO)

        # Prepare a create payload wrapped in an AST structure.
        payload = {
            "ast": {
                "query": {
                    "type": "create",
                    "data": {
                        "name": "TestOperationDummy",
                        "value": 123,
                        "related": self.related_dummy.id,
                    },
                }
            }
        }
        url = reverse("modelsync:model_view", args=["django_app.DummyModel"])

        # Send the POST request with the X-OPERATION-ID header.
        response = self.client.post(
            url, data=payload, format="json", HTTP_X_OPERATION_ID="test-operation-123"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(DummyModel.objects.filter(name="TestOperationDummy").exists())

        # Check the captured log records for the operation_id.
        matching_records = [
            record
            for record in capture_handler.records
            if "Emitted event" in record.getMessage()
        ]
        self.assertTrue(len(matching_records) > 0, "No event log record found.")
        # Now assert that the operation_id appears in the log record.
        log_message = matching_records[0].getMessage()
        self.assertIn("'operation_id': 'test-operation-123'", log_message)

        # Clean up by removing the handler.
        logger.removeHandler(capture_handler)
