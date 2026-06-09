"""Root URL configuration."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy

from accounts.forms import EmailLoginForm, ResendPasswordResetForm
from accounts.views import register
from competition import views as comp_views
from competition.cron import send_reminders_endpoint

urlpatterns = [
    path("admin/", admin.site.urls),
    # Organiser Manage area (on-brand; gated to superuser/Organiser group).
    path("manage/", include("competition.manage_urls")),
    # Auth (email/password; pluggable for Phase II social logins).
    path("accounts/register/", register, name="register"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            authentication_form=EmailLoginForm,
        ),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Forgot-password flow. Email is sent via our Resend layer (ResendPasswordResetForm).
    path(
        "accounts/password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            subject_template_name="registration/password_reset_subject.txt",
            form_class=ResendPasswordResetForm,
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    # Change password while logged in.
    path(
        "accounts/password-change/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/password_change_form.html",
            success_url=reverse_lazy("password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "accounts/password-change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/password_change_done.html"
        ),
        name="password_change_done",
    ),
    # Player app
    path("", comp_views.dashboard, name="dashboard"),
    path("week/<int:week_number>/entry/", comp_views.entry, name="entry"),
    path("week/<int:week_number>/my-entry/", comp_views.my_entry, name="my_entry"),
    path(
        "week/<int:week_number>/team/<int:participant_id>/",
        comp_views.team_entry,
        name="team_entry",
    ),
    path(
        "week/<int:week_number>/leaderboard/",
        comp_views.weekly_leaderboard,
        name="weekly_leaderboard",
    ),
    path(
        "leaderboard/season/",
        comp_views.season_leaderboard,
        name="season_leaderboard",
    ),
    path("team/<int:participant_id>/season/", comp_views.season_team, name="season_team"),
    # Vercel Cron endpoint for reminders (secured by CRON_SECRET).
    path("cron/send-reminders/", send_reminders_endpoint, name="cron_send_reminders"),
]
