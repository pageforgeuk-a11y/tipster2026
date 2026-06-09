"""URLs for the organiser Manage area (namespace: 'manage')."""

from django.urls import path

from . import manage_views

app_name = "manage"

urlpatterns = [
    path("", manage_views.dashboard, name="dashboard"),
    path("week/<int:gw_id>/action/", manage_views.week_action, name="week_action"),
    path("week/<int:gw_id>/results/", manage_views.results, name="results"),
    path("week/<int:gw_id>/reconcile/", manage_views.reconcile, name="reconcile"),
]
