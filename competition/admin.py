"""Organiser tooling.

Most of the per-week setup (fixtures, T/F questions, deadline) is the stock
Django admin with inlines. Step 5 of the admin workflow — entering results —
gets a bespoke screen (`results/<id>/`) because the stock admin is clumsy for
score + goalscorers + T/F + provider auto-fill + override in one place (spec §7).
"""

from django import forms
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from . import players as player_resolution
from . import services
from .models import (
    Entry,
    Fixture,
    FixtureGoal,
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
from .providers import get_results_provider

# Shared <datalist> ids wired up by GameWeekAdmin's change form (see
# templates/admin/competition/gameweek/change_form.html).
TEAM_DATALIST_ID = "team-suggestions"
PLAYER_DATALIST_ID = "player-suggestions"
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

    # --- custom URLs ---------------------------------------------------------

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:gw_id>/results/",
                self.admin_site.admin_view(self.results_entry_view),
                name="competition_gameweek_results",
            ),
            path(
                "<int:gw_id>/reconcile/",
                self.admin_site.admin_view(self.reconcile_view),
                name="competition_gameweek_reconcile",
            ),
        ]
        return custom + urls

    @admin.display(description="Results")
    def results_links(self, obj):
        url = reverse("admin:competition_gameweek_results", args=[obj.id])
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

    # --- bespoke results-entry screen ---------------------------------------

    def results_entry_view(self, request, gw_id):
        game_week = get_object_or_404(GameWeek, pk=gw_id)
        fixtures = list(game_week.fixtures.all())
        questions = list(game_week.questions.all())

        if request.method == "POST":
            action = request.POST.get("action", "save")

            if action == "autofill":
                self._autofill(request, game_week, fixtures)
                return redirect(request.path)

            self._save_results(request, game_week, fixtures, questions)
            # New players created from results may now resolve previously
            # unknown/ambiguous picks — re-run pick resolution for the week.
            self._reresolve_picks(game_week)

            if action == "finalise":
                services.recompute_game_week(game_week)
                game_week.status = GameWeek.Status.FINALISED
                game_week.save(update_fields=["status"])
                messages.success(
                    request,
                    "Results saved, all entries rescored, and the week finalised.",
                )
                return redirect("admin:competition_gameweek_changelist")

            # plain save
            if game_week.status in (GameWeek.Status.OPEN, GameWeek.Status.LOCKED):
                game_week.status = GameWeek.Status.RESULTS_IN
                game_week.save(update_fields=["status"])
            messages.success(request, "Results saved (not yet finalised).")
            return redirect(request.path)

        # Pre-load existing goalscorers per fixture, with each scorer's team
        # pre-selected from the linked Player where known.
        for fixture in fixtures:
            fixture.team_options = [fixture.home_team, fixture.away_team]
            rows = []
            for g in fixture.goals.all():
                selected = ""
                if g.player:
                    label = g.player.national_team if game_week.is_international else g.player.club
                    if label in fixture.team_options:
                        selected = label
                rows.append({"goal": g, "selected_team": selected})
            fixture.goal_rows = rows

        provider = get_results_provider()
        context = {
            **self.admin_site.each_context(request),
            "title": f"Enter results — GW{game_week.week_number}",
            "game_week": game_week,
            "fixtures": fixtures,
            "questions": questions,
            "provider_name": provider.name,
            "provider_configured": provider.is_configured(),
            "player_suggestions": self._player_labels(game_week),
            "player_datalist_id": PLAYER_DATALIST_ID,
            "unresolved_count": self._unresolved_picks(game_week).count(),
            "opts": self.model._meta,
        }
        return render(request, "admin/results_entry.html", context)

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _player_labels(game_week):
        return [
            p.label(international=game_week.is_international)
            for p in Player.objects.filter(is_active=True)
        ]

    @staticmethod
    def _unresolved_picks(game_week):
        """Submitted picks for the week that have text but no confident Player."""
        return ScorerPick.objects.filter(
            entry__game_week=game_week,
            entry__submitted_at__isnull=False,
            player__isnull=True,
        ).exclude(player_name="")

    @staticmethod
    def _reresolve_picks(game_week):
        for pick in ScorerPick.objects.filter(
            entry__game_week=game_week, player__isnull=True
        ).exclude(player_name=""):
            player, needs_review = player_resolution.resolve_for_pick(pick.player_name)
            if player or needs_review != pick.needs_review:
                pick.player = player
                pick.needs_review = needs_review
                pick.save(update_fields=["player", "needs_review"])

    def _save_results(self, request, game_week, fixtures, questions):
        for fixture in fixtures:
            home = request.POST.get(f"fixture_{fixture.id}_home", "").strip()
            away = request.POST.get(f"fixture_{fixture.id}_away", "").strip()
            fixture.actual_home_score = int(home) if home.isdigit() else None
            fixture.actual_away_score = int(away) if away.isdigit() else None
            fixture.save(update_fields=["actual_home_score", "actual_away_score"])

            # Goalscorers: replace the set from the posted rows.
            fixture.goals.all().delete()
            names = request.POST.getlist(f"scorer_name_{fixture.id}")
            counts = request.POST.getlist(f"scorer_goals_{fixture.id}")
            teams = request.POST.getlist(f"scorer_team_{fixture.id}")
            pens = set(request.POST.getlist(f"scorer_pen_{fixture.id}"))
            for idx, name in enumerate(names):
                name = name.strip()
                if not name:
                    continue
                count = counts[idx] if idx < len(counts) else "1"
                team_hint = teams[idx].strip() if idx < len(teams) else ""
                player = player_resolution.resolve_or_create(
                    name,
                    club=None if game_week.is_international else team_hint,
                    national_team=team_hint if game_week.is_international else None,
                )
                FixtureGoal.objects.create(
                    fixture=fixture,
                    player=player,
                    player_name=name,
                    goals=int(count) if count.isdigit() and int(count) > 0 else 1,
                    is_penalty=str(idx) in pens,
                )

        for question in questions:
            val = request.POST.get(f"tf_{question.id}", "")
            if val == "true":
                question.correct_answer = True
            elif val == "false":
                question.correct_answer = False
            else:
                question.correct_answer = None
            question.save(update_fields=["correct_answer"])

    def _autofill(self, request, game_week, fixtures):
        provider = get_results_provider()
        if not provider.is_configured():
            messages.warning(
                request,
                f"No results provider configured ({provider.name}); enter results "
                "manually.",
            )
            return
        filled = 0
        for fixture in fixtures:
            if not fixture.external_match_id:
                continue
            result = provider.fetch_result(fixture.external_match_id)
            if result is None:
                continue
            fixture.actual_home_score = result.home_score
            fixture.actual_away_score = result.away_score
            fixture.save(update_fields=["actual_home_score", "actual_away_score"])
            fixture.goals.all().delete()
            for s in result.scorers:
                player = player_resolution.resolve_or_create(
                    s.player_name,
                    club=None if game_week.is_international else s.team,
                    national_team=s.team if game_week.is_international else None,
                    external_player_id=s.external_player_id,
                )
                FixtureGoal.objects.create(
                    fixture=fixture,
                    player=player,
                    player_name=s.player_name,
                    goals=s.goals,
                    is_penalty=s.is_penalty,
                    minute=s.minute,
                )
            filled += 1
        self._reresolve_picks(game_week)
        messages.success(
            request,
            f"Auto-filled {filled} fixture(s) from {provider.name}. "
            "Review and override anything before finalising.",
        )

    # --- pick reconciliation -------------------------------------------------

    def reconcile_view(self, request, gw_id):
        """Map unresolved/ambiguous scorer picks to a canonical Player."""
        game_week = get_object_or_404(GameWeek, pk=gw_id)

        if request.method == "POST":
            updated = 0
            created = 0
            for pick in self._unresolved_picks(game_week):
                raw = request.POST.get(f"pick_{pick.id}", "").strip()
                if not raw:
                    continue
                if raw == "new":
                    # Create (or match) a Player from the typed text, optionally
                    # with a club typed in the row's club box for disambiguation.
                    name, club_from_text = player_resolution.parse_label(
                        pick.player_name
                    )
                    club = (
                        request.POST.get(f"new_club_{pick.id}", "").strip()
                        or club_from_text
                    )
                    before = Player.objects.count()
                    player = player_resolution.resolve_or_create(name, club=club)
                    if Player.objects.count() > before:
                        created += 1
                else:
                    player = (
                        Player.objects.filter(pk=raw).first() if raw.isdigit() else None
                    )
                if player:
                    pick.player = player
                    pick.needs_review = False
                    pick.save(update_fields=["player", "needs_review"])
                    updated += 1
            msg = f"Reconciled {updated} pick(s)."
            if created:
                msg += f" Created {created} new player(s)."
            messages.success(request, msg)
            if request.POST.get("then") == "finalise":
                services.recompute_game_week(game_week)
                game_week.status = GameWeek.Status.FINALISED
                game_week.save(update_fields=["status"])
                messages.success(request, "Week finalised and rescored.")
                return redirect("admin:competition_gameweek_changelist")
            return redirect(request.path)

        rows = []
        for pick in self._unresolved_picks(game_week).select_related(
            "entry__participant"
        ):
            suggestions = player_resolution._candidates(
                player_resolution.parse_label(pick.player_name)[0], active_only=True
            )
            rows.append({"pick": pick, "suggestions": suggestions})

        context = {
            **self.admin_site.each_context(request),
            "title": f"Reconcile picks — GW{game_week.week_number}",
            "game_week": game_week,
            "rows": rows,
            "all_players": Player.objects.filter(is_active=True),
            "opts": self.model._meta,
        }
        return render(request, "admin/reconcile_picks.html", context)


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
