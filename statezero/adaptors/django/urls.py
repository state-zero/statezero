from django.urls import path

from .views import EventsAuthView, ModelListView, ModelView, SchemaView, FileUploadView, FastUploadView, ActionSchemaView, ActionView, ValidateView, FieldPermissionsView

app_name = "statezero"

urlpatterns = [
    path("events/auth/", EventsAuthView.as_view(), name="events_auth"),
    path("models/", ModelListView.as_view(), name="model_list"),
    path("files/upload/", FileUploadView.as_view(), name="file_upload"),
    path("files/fast-upload/", FastUploadView.as_view(), name="fast_file_upload"),
    path("actions/<str:action_name>/", ActionView.as_view(), name="action"),
    path("actions-schema/", ActionSchemaView.as_view(), name="actions_schema"),
    path("<str:model_name>/validate/", ValidateView.as_view(), name="validate"),
    path("<str:model_name>/field-permissions/", FieldPermissionsView.as_view(), name="field_permissions"),
    path("<str:model_name>/get-schema/", SchemaView.as_view(), name="schema_view"),
    path("<str:model_name>/", ModelView.as_view(), name="model_view"),
]
