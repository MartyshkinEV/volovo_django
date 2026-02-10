from django.urls import path
from . import views

urlpatterns = [
    path("oids", views.oids, name="oids"),
    path("routes", views.routes, name="routes"),
    path("points_summary", views.points_summary, name="points_summary"),
    path("trips_for_map", views.trips_for_map, name="trips_for_map"),
    path("forms/save", views.forms_save, name="forms_save"),
    path("forms/<str:form_id>/export_xlsx", views.forms_export_xlsx, name="forms_export_xlsx"),
]

