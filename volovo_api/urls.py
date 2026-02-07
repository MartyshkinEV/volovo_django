from django.urls import path
from . import views

urlpatterns = [
    path("routes", views.api_routes),
    path("oids", views.api_oids),
    path("points_summary", views.points_summary),
    path("trips_for_map", views.trips_for_map),

    # forms
    path("forms/save", views.forms_save),
    path("forms", views.forms_list),
    path("forms/<int:form_id>", views.forms_get),
    path("forms/<int:form_id>/export_xlsx", views.forms_export_xlsx),
]
