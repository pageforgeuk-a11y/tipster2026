"""On-brand organiser "Manage" area (Phase A).

Access is gated to superusers or members of the "Organiser" group. This is the
day-to-day organiser tool; the stock Django admin remains for the superuser as a
low-level fallback.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from . import results_ops, services
from .models import Entry, GameWeek, Participant, Player, ScorerPick, Season
from .providers import get_results_provider

ORGANISER_GROUP = "Organiser"


def is_organiser(user) -> bool:
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name=ORGANISER_GROUP).exists()
    )


def organiser_required(view):
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_organiser(request.user):
            raise PermissionDenied("Organiser access required.")
        return view(request, *args, **kwargs)

    return _wrapped


@organiser_required
def dashboard(request):
    season = Season.objects.filter(is_active=True).first()
    weeks = []
    if season:
        weeks = list(
            GameWeek.objects.filter(season=season)
            .order_by("week_number")
            .prefetch_related("fixtures", "questions")
        )
        submitted = dict(
            Entry.objects.filter(game_week__season=season, submitted_at__isnull=False)
            .values_list("game_week")
            .annotate(c=Count("id"))
        )
        unresolved = dict(
            ScorerPick.objects.filter(
                entry__game_week__season=season,
                entry__submitted_at__isnull=False,
                player__isnull=True,
            )
            .exclude(player_name="")
            .values_list("entry__game_week")
            .annotate(c=Count("id"))
        )
        for w in weeks:
            fixtures = list(w.fixtures.all())
            questions = list(w.questions.all())
            w.submitted_count = submitted.get(w.id, 0)
            w.unresolved_count = unresolved.get(w.id, 0)
            w.fixture_count = len(fixtures)
            w.question_count = len(questions)
            # Nudge: deadline gone but not finalised yet.
            w.needs_attention = (
                w.is_past_deadline and w.status != GameWeek.Status.FINALISED
            ) or w.unresolved_count > 0

    return render(
        request,
        "competition/manage/dashboard.html",
        {
            "season": season,
            "weeks": weeks,
            "participant_count": (
                Participant.objects.filter(season=season).count() if season else 0
            ),
            "player_count": Player.objects.filter(is_active=True).count(),
        },
    )


@organiser_required
def week_action(request, gw_id):
    """Quick status changes from the dashboard (open / lock / finalise)."""
    game_week = get_object_or_404(GameWeek, pk=gw_id)
    if request.method != "POST":
        return redirect("manage:dashboard")
    action = request.POST.get("action")
    if action == "open":
        game_week.status = GameWeek.Status.OPEN
        game_week.save(update_fields=["status"])
        messages.success(request, f"GW{game_week.week_number} opened to players.")
    elif action == "lock":
        game_week.status = GameWeek.Status.LOCKED
        game_week.save(update_fields=["status"])
        messages.success(request, f"GW{game_week.week_number} locked.")
    elif action == "finalise":
        services.recompute_game_week(game_week)
        game_week.status = GameWeek.Status.FINALISED
        game_week.save(update_fields=["status"])
        messages.success(
            request, f"GW{game_week.week_number} finalised and rescored."
        )
    return redirect("manage:dashboard")


@organiser_required
def results(request, gw_id):
    game_week = get_object_or_404(GameWeek, pk=gw_id)
    fixtures = list(game_week.fixtures.all())
    questions = list(game_week.questions.all())

    if request.method == "POST":
        action = request.POST.get("action", "save")

        if action == "autofill":
            outcome = results_ops.autofill(game_week, fixtures)
            if not outcome["configured"]:
                messages.warning(
                    request,
                    f"No results provider configured ({outcome['provider_name']}); "
                    "enter results manually.",
                )
            else:
                messages.success(
                    request,
                    f"Auto-filled {outcome['filled']} fixture(s) from "
                    f"{outcome['provider_name']}. Review and override before finalising.",
                )
            return redirect("manage:results", gw_id=gw_id)

        results_ops.save_results(request.POST, game_week, fixtures, questions)
        results_ops.reresolve_picks(game_week)

        if action == "finalise":
            services.recompute_game_week(game_week)
            game_week.status = GameWeek.Status.FINALISED
            game_week.save(update_fields=["status"])
            messages.success(
                request, "Results saved, all entries rescored, and the week finalised."
            )
            return redirect("manage:dashboard")

        if game_week.status in (GameWeek.Status.OPEN, GameWeek.Status.LOCKED):
            game_week.status = GameWeek.Status.RESULTS_IN
            game_week.save(update_fields=["status"])
        messages.success(request, "Results saved (not yet finalised).")
        return redirect("manage:results", gw_id=gw_id)

    results_ops.fixture_goal_rows(game_week, fixtures)
    provider = get_results_provider()
    return render(
        request,
        "competition/manage/results.html",
        {
            "game_week": game_week,
            "fixtures": fixtures,
            "questions": questions,
            "provider_name": provider.name,
            "provider_configured": provider.is_configured(),
            "player_suggestions": results_ops.player_labels(game_week),
            "player_datalist_id": "player-suggestions",
            "unresolved_count": results_ops.unresolved_picks(game_week).count(),
        },
    )


@organiser_required
def reconcile(request, gw_id):
    game_week = get_object_or_404(GameWeek, pk=gw_id)

    if request.method == "POST":
        updated, created = results_ops.apply_reconcile(request.POST, game_week)
        msg = f"Reconciled {updated} pick(s)."
        if created:
            msg += f" Created {created} new player(s)."
        messages.success(request, msg)
        if request.POST.get("then") == "finalise":
            services.recompute_game_week(game_week)
            game_week.status = GameWeek.Status.FINALISED
            game_week.save(update_fields=["status"])
            messages.success(request, "Week finalised and rescored.")
            return redirect("manage:dashboard")
        return redirect("manage:reconcile", gw_id=gw_id)

    return render(
        request,
        "competition/manage/reconcile.html",
        {
            "game_week": game_week,
            "rows": results_ops.reconcile_rows(game_week),
            "all_players": Player.objects.filter(is_active=True),
        },
    )
