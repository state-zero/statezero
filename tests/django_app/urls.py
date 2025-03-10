from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "modelsync/", include("modelsync.adaptors.django.urls", namespace="modelsync")
    ),
]
