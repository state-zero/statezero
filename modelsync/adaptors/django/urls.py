from django.urls import path

from .views import EventsAuthView, ModelListView, ModelView, SchemaView

app_name = "modelsync"

urlpatterns = [
    path("models/", ModelListView.as_view(), name="model_list"),
    path("<str:model_name>/", ModelView.as_view(), name="model_view"),
    path("<str:model_name>/get-schema/", SchemaView.as_view(), name="schema_view"),
    path("events/auth/", EventsAuthView.as_view(), name="events_auth"),
]
