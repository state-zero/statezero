from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase


class ActionAutoSerializerApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")
        self.assignee = User.objects.create_user(username="assignee", password="password")
        self.reviewer = User.objects.create_user(username="reviewer", password="password")
        self.url = reverse("statezero:action", args=["auto_create_ticket"])

    def _base_payload(self):
        return {
            "title": "Investigate regression",
            "priority": 3,
            "due_at": "2026-02-01T10:30:00Z",
            "tags": ["backend", "urgent"],
            "metadata": {"source": "api"},
            "assignee": self.assignee.pk,
            "reviewers": [self.reviewer.pk],
        }

    def test_missing_required_field(self):
        payload = self._base_payload()
        payload.pop("title")
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("title", response.data["detail"])

    def test_invalid_datetime_format(self):
        payload = self._base_payload()
        payload["due_at"] = "not-a-date"
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("due_at", response.data["detail"])

    def test_invalid_foreign_key(self):
        payload = self._base_payload()
        payload["assignee"] = 999999
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("assignee", response.data["detail"])

    def test_invalid_many_to_many_list(self):
        payload = self._base_payload()
        payload["reviewers"] = ["not-an-id"]
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("reviewers", response.data["detail"])

    def test_invalid_tags_type(self):
        payload = self._base_payload()
        payload["tags"] = "backend"
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("tags", response.data["detail"])
