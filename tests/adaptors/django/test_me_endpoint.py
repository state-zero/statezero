from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase


class MeEndpointTest(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="me_test_user",
            password="password123",
            email="me@example.com",
        )
        self.url = reverse("statezero:me")

    def test_me_returns_summary_for_authenticated_user(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["model_name"], "auth.user")
        self.assertIn("data", response.data)
        self.assertEqual(set(response.data["data"].keys()), {"id", "repr"})
        self.assertEqual(response.data["data"]["id"], self.user.id)
        self.assertIn("str", response.data["data"]["repr"])
        self.assertIn("img", response.data["data"]["repr"])

    def test_me_requires_authenticated_user(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
