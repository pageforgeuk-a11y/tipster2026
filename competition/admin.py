"""Organiser tooling.

Most of the per-week setup (fixtures, T/F questions, deadline) is the stock
Django admin with inlines. Step 5 of the admin workflow — entering results —
gets a bespoke screen (`results/<id>/`) because the stock admin is clumsy for
score + goalscorers + T/F + provider auto-fill + override in one place (spec §7).
"""

from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from . import players as player_resolution
from . import services
from .models import (
    Entry,
    Fixture,
    GameWeek,
    MatchPrediction,
    Participant,
    Player,
    QuestionTemplate,
    ScorerPick,
    Season,
    SeasonScore,
    Team,
    TrueFalseAnswer,
    TrueFalseQuestion,
    WeeklyScore,
)

# Shared <datalist> ids wired up by GameWeekAdmin's change form (see
# templates/admin/competition/gameweek/change_form.html).
TEAM_DATALIST_ID = "team-suggestions"
QUESTION_DATALIST_ID = "question-suggestions"


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "club", "national_team", "is_active", "external_player_id")
    list_filter = ("is_active",)
    search_fields = ("full_name", "club", "national_team", "external_player_id")
    actions = ["merge_into_first"]

    @admin.action(description="Merge selected players into the first (by name)")
    def merge_into_first(self, request, queryset):
        players = list(queryset.order_by("full_name", "id"))
        if len(players) < 2:
            self.message_user(
                request, "Select two or more players to merge.", level=messages.WARNING
            )
            return
        primary, duplicates = players[0], players[1:]
        merged = player_resolution.merge_players(primary, duplicates)
        self.message_user(
            request,
            f"Merged {merged} player(s) into “{primary}”. Re-finalise affected "
            "weeks to refresh scores.",
        )


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "is_active", "external_team_id")
    list_filter = ("is_active",)
    search_fields = ("name", "short_name")


@admin.register(QuestionTemplate)
class QuestionTemplateAdmin(admin.ModelAdmin):
    list_display = ("text", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("text",)


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "is_active")
    list_filter = ("is_active",)


class FixtureInlineForm(forms.ModelForm):
    """Free-text team inputs backed by an autocomplete datalist of known teams."""

    class Meta:
        model = Fixture
        fields = "__all__"
        widgets = {
            "home_team": forms.TextInput(
                attrs={"list": TEAM_DATALIST_ID, "autocomplete": "off"}
            ),
            "away_team": forms.TextInput(
                attrs={"list": TEAM_DATALIST_ID, "autocomplete": "off"}
            ),
        }


class FixtureInline(admin.TabularInline):
    model = Fixture
    form = FixtureInlineForm
    extra = 0
    fields = ("order", "home_team", "away_team", "kickoff", "external_match_id")
    ordering = ("order",)


class TrueFalseQuestionInlineForm(forms.ModelForm):
    """Free-text question input backed by an autocomplete bank of past questions."""

    class Meta:
        model = TrueFalseQuestion
        fields = "__all__"
        widgets = {
            "text": forms.TextInput(
                attrs={
                    "list": QUESTION_DATALIST_ID,
                    "autocomplete": "off",
                    "size": 70,
                }
            )
        }


class TrueFalseQuestionInline(admin.TabularInline):
    model = TrueFalseQuestion
    form = TrueFalseQuestionInlineForm
    extra = 0
    fields = ("order", "text")
    ordering = ("order",)


@admin.register(GameWeek)
class GameWeekAdmin(admin.ModelAdmin):
    list_display = (
        "week_number",
        "season",
        "title",
        "deadline",
        "status",
        "results_links",
    )
    list_filter = ("season", "status")
    ordering = ("season", "week_number")
    inlines = [FixtureInline, TrueFalseQuestionInline]
    actions = ["action_open", "action_lock", "action_finalise"]
    change_form_template = "admin/competition/gameweek/change_form.html"

    def _changeform_view(self, request, object_id, form_url, extra_context):
        # Supply the team-name suggestions for the autocomplete datalist.
        extra_context = extra_context or {}
        extra_context["team_suggestions"] = list(
            Team.objects.filter(is_active=True).values_list("name", flat=True)
        )
        extra_context["team_datalist_id"] = TEAM_DATALIST_ID
        extra_context["question_suggestions"] = list(
            QuestionTemplate.objects.filter(is_active=True).values_list(
                "text", flat=True
            )
        )
        extra_context["question_datalist_id"] = QUESTION_DATALIST_ID
        return super()._changeform_view(request, object_id, form_url, extra_context)

    @admin.display(description="Results")
    def results_links(self, obj):
        # Results entry now lives in the on-brand Manage area.
        url = reverse("manage:results", args=[obj.id])
        return format_html('<a class="button" href="{}">Enter results</a>', url)

    # --- status actions ------------------------------------------------------

    @admin.action(description="Open selected week(s) to players")
    def action_open(self, request, queryset):
        updated = queryset.update(status=GameWeek.Status.OPEN)
        self.message_user(request, f"Opened {updated} week(s).")

    @admin.action(description="Lock selected week(s)")
    def action_lock(self, request, queryset):
        updated = queryset.update(status=GameWeek.Status.LOCKED)
        self.message_user(request, f"Locked {updated} week(s).")

    @admin.action(description="Finalise selected week(s) (rescore)")
    def action_finalise(self, request, queryset):
        count = queryset.count()
        for gw in queryset:
            services.recompute_game_week(gw)
            gw.status = GameWeek.Status.FINALISED
            gw.save(update_fields=["status"])
        self.message_user(request, f"Finalised and rescored {count} week(s).")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("display_name", "real_name", "email", "season", "join_week")
    list_filter = ("season",)
    search_fields = (
        "display_name",
        "user__first_name",
        "user__last_name",
        "user__email",
    )

    @admin.display(description="Name")
    def real_name(self, obj):
        return obj.user.get_full_name() or "—"

    @admin.display(description="Email / login")
    def email(self, obj):
        return obj.user.email


class MatchPredictionInline(admin.TabularInline):
    model = MatchPrediction
    extra = 0


class TrueFalseAnswerInline(admin.TabularInline):
    model = TrueFalseAnswer
    extra = 0


class ScorerPickInline(admin.TabularInline):
    model = ScorerPick
    extra = 0


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    """Admin can view all entries (spec §3)."""

    list_display = ("participant", "game_week", "submitted_at", "is_locked")
    list_filter = ("game_week__season", "game_week", "is_locked")
    search_fields = ("participant__display_name",)
    inlines = [MatchPredictionInline, TrueFalseAnswerInline, ScorerPickInline]


@admin.register(WeeklyScore)
class WeeklyScoreAdmin(admin.ModelAdmin):
    list_display = (
        "participant",
        "game_week",
        "s1",
        "s2",
        "s3",
        "s4",
        "total",
        "is_non_entry_default",
    )
    list_filter = ("game_week__season", "game_week")
    search_fields = ("participant__display_name",)


@admin.register(SeasonScore)
class SeasonScoreAdmin(admin.ModelAdmin):
    list_display = ("participant", "season", "total", "s1_total")
    list_filter = ("season",)
    search_fields = ("participant__display_name",)
