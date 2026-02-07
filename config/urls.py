from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),          # админка
    path("dj/api/", include("volovo_api.urls")),  # твой API
]

