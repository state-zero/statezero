from django.urls import path

from .views import EventsAuthView, ModelListView, ModelView, SchemaView, BatchView, HotPathView

app_name = "statezero"

urlpatterns = [
    path("events/auth/", EventsAuthView.as_view(), name="events_auth"),
    path("hotpath/channels/", HotPathView.as_view(), name="hot_path_view"),
    path("batch/", BatchView.as_view(), name="batch_view"),
    path("models/", ModelListView.as_view(), name="model_list"),
    path("<str:model_name>/", ModelView.as_view(), name="model_view"),
    path("<str:model_name>/get-schema/", SchemaView.as_view(), name="schema_view")
]
