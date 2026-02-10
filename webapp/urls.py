from django.urls import path
from .views import putevoy_page

urlpatterns = [
    path("", putevoy_page, name="putevoy"),
]
