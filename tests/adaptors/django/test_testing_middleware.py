from contextlib import contextmanager

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APITestCase

from statezero.adaptors.django.testing import AllowAllFieldsPermission, TestSeedingMiddleware
from statezero.adaptors.django.config import registry
from tests.django_app.models import CustomPKModel, DummyModel, DummyRelatedModel


_CONTEXT_CALLED = False


def test_context_factory(request):
    @contextmanager
    def _ctx():
        global _CONTEXT_CALLED
        _CONTEXT_CALLED = True
        yield
    return _ctx()


class TestSeedingMiddlewarePermissions(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")
        self.custom = CustomPKModel.objects.create(custom_pk=1, name="Original")

    @override_settings(STATEZERO_TEST_MODE=True, MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "corsheaders.middleware.CorsMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "statezero.adaptors.django.middleware.OperationIDMiddleware",
        "statezero.adaptors.django.testing.TestSeedingMiddleware",
    ])
    def test_seeding_header_allows_update(self):
        url = reverse("statezero:model_view", args=["django_app.CustomPKModel"])
        payload = {
            "ast": {
                "query": {
                    "type": "update",
                    "filter": {"type": "filter", "conditions": {"custom_pk": 1}},
                    "data": {"name": "Updated"},
                }
            }
        }

        # Without header, should be denied (ReadOnlyPermission)
        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 403)

        # With seeding header, should be allowed
        response = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_TEST_SEEDING="1",
        )
        self.assertEqual(response.status_code, 200)
        self.custom.refresh_from_db()
        self.assertEqual(self.custom.name, "Updated")

    @override_settings(STATEZERO_TEST_MODE=True, MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "corsheaders.middleware.CorsMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "statezero.adaptors.django.middleware.OperationIDMiddleware",
        "statezero.adaptors.django.testing.TestSeedingMiddleware",
    ])
    def test_reset_header_purges_registered_models(self):
        DummyRelatedModel.objects.create(name="Related")
        DummyModel.objects.create(name="Dummy", value=1)
        self.assertEqual(DummyModel.objects.count(), 1)

        url = reverse("statezero:model_list")
        response = self.client.get(url, HTTP_X_TEST_RESET="1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DummyModel.objects.count(), 0)
        self.assertEqual(DummyRelatedModel.objects.count(), 0)


class TestSeedingMiddlewareHooks(TestCase):
    @override_settings(
        STATEZERO_TEST_MODE=True,
        STATEZERO_TEST_REQUEST_CONTEXT="tests.adaptors.django.test_testing_middleware.test_context_factory",
    )
    def test_request_context_factory_is_called(self):
        global _CONTEXT_CALLED
        _CONTEXT_CALLED = False

        def view(request):
            return None

        rf = RequestFactory()
        request = rf.get("/statezero/models/")
        middleware = TestSeedingMiddleware(view)
        middleware(request)

        self.assertTrue(_CONTEXT_CALLED)

    @override_settings(STATEZERO_TEST_MODE=True)
    def test_seeding_fields_header_uses_allow_all_fields_permission(self):
        rf = RequestFactory()
        request = rf.get("/statezero/models/", HTTP_X_TEST_SEEDING="1", HTTP_X_TEST_SEEDING_FIELDS="1")

        model_config = registry.get_config(CustomPKModel)
        original = model_config._permissions

        def view(request):
            # Should be swapped during request
            self.assertEqual(model_config._permissions, [AllowAllFieldsPermission])
            return None

        middleware = TestSeedingMiddleware(view)
        middleware(request)

        # Ensure restored
        self.assertEqual(model_config._permissions, original)
