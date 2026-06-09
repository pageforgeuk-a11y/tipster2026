"""URLs for the organiser Manage area (namespace: 'manage')."""

from django.urls import path

from . import manage_views

app_name = "manage"

urlpatterns = [
    path("", manage_views.dashboard, name="dashboard"),
    path("week/new/", manage_views.week_new, name="week_new"),
    path("week/<int:gw_id>/setup/", manage_views.week_setup, name="week_setup"),
    path("week/<int:gw_id>/action/", manage_views.week_action, name="week_action"),
    path("week/<int:gw_id>/results/", manage_views.results, name="results"),
    path("week/<int:gw_id>/reconcile/", manage_views.reconcile, name="reconcile"),
    # Players
    path("players/", manage_views.players, name="players"),
    path("players/new/", manage_views.player_new, name="player_new"),
    path("players/merge/", manage_views.players_merge, name="players_merge"),
    path("players/<int:pk>/", manage_views.player_edit, name="player_edit"),
    path("players/<int:pk>/delete/", manage_views.player_delete, name="player_delete"),
    # Teams
    path("teams/", manage_views.teams, name="teams"),
    path("teams/new/", manage_views.team_new, name="team_new"),
    path("teams/<int:pk>/", manage_views.team_edit, name="team_edit"),
    path("teams/<int:pk>/delete/", manage_views.team_delete, name="team_delete"),
    # Question bank
    path("questions/", manage_views.questions, name="questions"),
    path("questions/new/", manage_views.question_new, name="question_new"),
    path("questions/<int:pk>/", manage_views.question_edit, name="question_edit"),
    path("questions/<int:pk>/delete/", manage_views.question_delete, name="question_delete"),
    # Participants
    path("participants/", manage_views.participants, name="participants"),
    path("participants/<int:pk>/", manage_views.participant_edit, name="participant_edit"),
    # Seasons
    path("seasons/", manage_views.seasons, name="seasons"),
    path("seasons/new/", manage_views.season_new, name="season_new"),
    path("seasons/<int:pk>/", manage_views.season_edit, name="season_edit"),
    path("seasons/<int:pk>/activate/", manage_views.season_activate, name="season_activate"),
    path("seasons/<int:pk>/archive/", manage_views.season_archive, name="season_archive"),
]
