"""
Test transport for the StateZero Python client.

Uses DRF's APIRequestFactory to send requests directly through the Django
view layer — no HTTP server needed.
"""


class DjangoTestTransport:
    """Transport that routes client calls through Django's ModelView directly."""

    def __init__(self, user):
        self.user = user

    def _raise_error(self, response):
        from statezero.client.runtime_template import _ERROR_MAP, StateZeroError
        data = response.data
        error_type = data.get("type", "")
        detail = data.get("detail", str(data))
        exc_cls = _ERROR_MAP.get(error_type, StateZeroError)
        raise exc_cls(detail)

    def post(self, model_name, body):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from statezero.adaptors.django.views import ModelView

        factory = APIRequestFactory()
        request = factory.post(
            f"/statezero/{model_name}/",
            data=body,
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ModelView.as_view()(request, model_name=model_name)
        response.render()

        if response.status_code >= 400:
            self._raise_error(response)

        return response.data

    def post_action(self, action_name, data):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from statezero.adaptors.django.views import ActionView

        factory = APIRequestFactory()
        request = factory.post(
            f"/statezero/actions/{action_name}/",
            data=data,
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ActionView.as_view()(request, action_name=action_name)
        response.render()

        if response.status_code >= 400:
            self._raise_error(response)

        return response.data

    def validate(self, model_name, data, validate_type="create", partial=False):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from statezero.adaptors.django.views import ValidateView

        factory = APIRequestFactory()
        request = factory.post(
            f"/statezero/{model_name}/validate/",
            data={"data": data, "validate_type": validate_type, "partial": partial},
            format="json",
        )
        force_authenticate(request, user=self.user)

        response = ValidateView.as_view()(request, model_name=model_name)
        response.render()

        if response.status_code >= 400:
            self._raise_error(response)

        return response.data

    def get_field_permissions(self, model_name):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from statezero.adaptors.django.views import FieldPermissionsView

        factory = APIRequestFactory()
        request = factory.get(f"/statezero/{model_name}/field-permissions/")
        force_authenticate(request, user=self.user)

        response = FieldPermissionsView.as_view()(request, model_name=model_name)
        response.render()

        if response.status_code >= 400:
            self._raise_error(response)

        return response.data

    def upload_file(self, file_data, filename, content_type):
        """Upload file through FileUploadView with filesystem storage."""
        import tempfile
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.files.storage import FileSystemStorage
        from rest_framework.test import APIRequestFactory, force_authenticate
        from statezero.adaptors.django.views import FileUploadView

        factory = APIRequestFactory()
        uploaded = SimpleUploadedFile(filename, file_data, content_type)
        request = factory.post(
            '/statezero/files/upload/',
            {'file': uploaded},
            format='multipart',
        )
        force_authenticate(request, user=self.user)

        fs = FileSystemStorage(location=tempfile.mkdtemp())
        with mock.patch("statezero.adaptors.django.views.default_storage", fs):
            response = FileUploadView.as_view()(request)
            response.render()

        if response.status_code >= 400:
            raise Exception(f"Upload error {response.status_code}: {response.data}")
        return response.data

    def upload_file_s3(self, file_data, filename, content_type):
        """S3 upload not available in test transport — falls back to direct upload."""
        return self.upload_file(file_data, filename, content_type)
