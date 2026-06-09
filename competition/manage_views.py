"""On-brand organiser "Manage" area (Phase A).

Access is gated to superusers or members of the "Organiser" group. This is the
day-to-day organiser tool; the stock Django admin remains for the superuser as a
low-level fallback.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.models import Group
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import players as player_resolution
from . import results_ops, services
from .forms import (
    GameWeekForm,
    ParticipantForm,
    PlayerForm,
    QuestionTemplateForm,
    SeasonForm,
    TeamForm,
)
from .models import (
    Entry,
    Fixture,
    GameWeek,
    Participant,
    Player,
    QuestionTemplate,
    ScorerPick,
    Season,
    Team,
    TrueFalseQuestion,
)
from .providers import get_results_provider

FIXTURE_COUNT = 10
QUESTION_COUNT = 8

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
def week_new(request):
    season = Season.objects.filter(is_active=True).first()
    if season is None:
        messages.error(request, "Create and activate a season before adding weeks.")
        return redirect("manage:dashboard")

    if request.method == "POST":
        form = GameWeekForm(request.POST)
        form.instance.season = season  # set before validation (unique week_number)
        if form.is_valid():
            game_week = form.save()
            messages.success(
                request,
                f"GW{game_week.week_number} created — now add fixtures and questions.",
            )
            return redirect("manage:week_setup", gw_id=game_week.id)
    else:
        last = GameWeek.objects.filter(season=season).order_by("-week_number").first()
        form = GameWeekForm(
            initial={"week_number": (last.week_number + 1) if last else 1}
        )

    return render(
        request, "competition/manage/week_new.html", {"form": form, "season": season}
    )


def _save_setup(post, game_week):
    """Persist the 10 fixtures and 8 questions from the setup form.

    A row with both team names (or question text) blank deletes any existing
    entry at that position; otherwise it's created/updated.
    """
    for order in range(1, FIXTURE_COUNT + 1):
        home = post.get(f"fix_{order}_home", "").strip()
        away = post.get(f"fix_{order}_away", "").strip()
        ext = post.get(f"fix_{order}_ext", "").strip()
        kickoff_raw = post.get(f"fix_{order}_kickoff", "").strip()
        existing = Fixture.objects.filter(game_week=game_week, order=order).first()
        if home or away:
            kickoff = None
            if kickoff_raw:
                dt = parse_datetime(kickoff_raw)
                if dt is not None:
                    kickoff = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
            Fixture.objects.update_or_create(
                game_week=game_week,
                order=order,
                defaults={
                    "home_team": home,
                    "away_team": away,
                    "external_match_id": ext,
                    "kickoff": kickoff,
                },
            )
        elif existing:
            existing.delete()

    for order in range(1, QUESTION_COUNT + 1):
        text = post.get(f"q_{order}", "").strip()
        existing = TrueFalseQuestion.objects.filter(
            game_week=game_week, order=order
        ).first()
        if text:
            TrueFalseQuestion.objects.update_or_create(
                game_week=game_week, order=order, defaults={"text": text}
            )
        elif existing:
            existing.delete()


@organiser_required
def week_setup(request, gw_id):
    game_week = get_object_or_404(GameWeek, pk=gw_id)

    if request.method == "POST":
        form = GameWeekForm(request.POST, instance=game_week)
        if form.is_valid():
            form.save()
            _save_setup(request.POST, game_week)
            messages.success(request, f"GW{game_week.week_number} setup saved.")
            return redirect("manage:dashboard")
    else:
        form = GameWeekForm(instance=game_week)

    fixtures = {f.order: f for f in game_week.fixtures.all()}
    questions = {q.order: q for q in game_week.questions.all()}
    fixture_rows = []
    for order in range(1, FIXTURE_COUNT + 1):
        f = fixtures.get(order)
        kickoff_val = (
            timezone.localtime(f.kickoff).strftime("%Y-%m-%dT%H:%M")
            if f and f.kickoff
            else ""
        )
        fixture_rows.append({"order": order, "f": f, "kickoff_val": kickoff_val})
    question_rows = [
        {"order": o, "q": questions.get(o)} for o in range(1, QUESTION_COUNT + 1)
    ]

    return render(
        request,
        "competition/manage/week_setup.html",
        {
            "game_week": game_week,
            "form": form,
            "fixture_rows": fixture_rows,
            "question_rows": question_rows,
            "team_suggestions": list(
                Team.objects.filter(is_active=True).values_list("name", flat=True)
            ),
            "question_suggestions": list(
                QuestionTemplate.objects.filter(is_active=True).values_list(
                    "text", flat=True
                )
            ),
        },
    )


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


# --- generic CRUD helpers ----------------------------------------------------


def _search(model, q, fields):
    qs = model.objects.all()
    if q:
        cond = Q()
        for f in fields:
            cond |= Q(**{f + "__icontains": q})
        qs = qs.filter(cond)
    return qs


def _modelform(request, form_class, instance, title, list_url, delete_url=None):
    if request.method == "POST":
        form = form_class(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "Saved.")
            return redirect(list_url)
    else:
        form = form_class(instance=instance)
    return render(
        request,
        "competition/manage/form.html",
        {
            "form": form,
            "title": title,
            "back_url": list_url,
            "delete_url": delete_url,
            "team_suggestions": _team_names(),
        },
    )


# --- players -----------------------------------------------------------------


@organiser_required
def players(request):
    q = request.GET.get("q", "").strip()
    rows = _search(Player, q, ["full_name", "club", "national_team"]).order_by(
        "full_name"
    )
    return render(
        request,
        "competition/manage/players.html",
        {"players": rows, "q": q, "team_suggestions": _team_names()},
    )


@organiser_required
def player_new(request):
    return _modelform(request, PlayerForm, None, "New player", reverse("manage:players"))


@organiser_required
def player_edit(request, pk):
    player = get_object_or_404(Player, pk=pk)
    return _modelform(
        request,
        PlayerForm,
        player,
        f"Edit {player.full_name}",
        reverse("manage:players"),
        delete_url=reverse("manage:player_delete", args=[pk]),
    )


@organiser_required
def player_delete(request, pk):
    if request.method == "POST":
        Player.objects.filter(pk=pk).delete()
        messages.success(request, "Player deleted.")
    return redirect("manage:players")


@organiser_required
def players_merge(request):
    ids = request.POST.getlist("ids")
    chosen = list(Player.objects.filter(id__in=ids).order_by("full_name", "id"))
    if len(chosen) < 2:
        messages.warning(request, "Select two or more players to merge.")
    else:
        primary, dupes = chosen[0], chosen[1:]
        merged = player_resolution.merge_players(primary, dupes)
        messages.success(
            request,
            f"Merged {merged} player(s) into “{primary}”. Re-finalise affected weeks "
            "to refresh scores.",
        )
    return redirect("manage:players")


def _team_names():
    return list(Team.objects.filter(is_active=True).values_list("name", flat=True))


# --- teams -------------------------------------------------------------------


@organiser_required
def teams(request):
    q = request.GET.get("q", "").strip()
    rows = _search(Team, q, ["name", "short_name"]).order_by("name")
    return render(request, "competition/manage/teams.html", {"teams": rows, "q": q})


@organiser_required
def team_new(request):
    return _modelform(request, TeamForm, None, "New team", reverse("manage:teams"))


@organiser_required
def team_edit(request, pk):
    team = get_object_or_404(Team, pk=pk)
    return _modelform(
        request,
        TeamForm,
        team,
        f"Edit {team.name}",
        reverse("manage:teams"),
        delete_url=reverse("manage:team_delete", args=[pk]),
    )


@organiser_required
def team_delete(request, pk):
    if request.method == "POST":
        Team.objects.filter(pk=pk).delete()
        messages.success(request, "Team deleted.")
    return redirect("manage:teams")


# --- question bank -----------------------------------------------------------


@organiser_required
def questions(request):
    q = request.GET.get("q", "").strip()
    rows = _search(QuestionTemplate, q, ["text"]).order_by("text")
    return render(
        request, "competition/manage/questions.html", {"questions": rows, "q": q}
    )


@organiser_required
def question_new(request):
    return _modelform(
        request, QuestionTemplateForm, None, "New question", reverse("manage:questions")
    )


@organiser_required
def question_edit(request, pk):
    item = get_object_or_404(QuestionTemplate, pk=pk)
    return _modelform(
        request,
        QuestionTemplateForm,
        item,
        "Edit question",
        reverse("manage:questions"),
        delete_url=reverse("manage:question_delete", args=[pk]),
    )


@organiser_required
def question_delete(request, pk):
    if request.method == "POST":
        QuestionTemplate.objects.filter(pk=pk).delete()
        messages.success(request, "Question deleted.")
    return redirect("manage:questions")


# --- participants ------------------------------------------------------------


@organiser_required
def participants(request):
    season = Season.objects.filter(is_active=True).first()
    rows = []
    if season:
        org_ids = set(
            Group.objects.get(name=ORGANISER_GROUP).user_set.values_list(
                "id", flat=True
            )
        )
        rows = list(
            Participant.objects.filter(season=season)
            .select_related("user")
            .order_by("display_name")
        )
        for p in rows:
            p.is_org = p.user_id in org_ids
    return render(
        request,
        "competition/manage/participants.html",
        {"participants": rows, "season": season},
    )


@organiser_required
def participant_edit(request, pk):
    participant = get_object_or_404(Participant, pk=pk)
    group = Group.objects.get(name=ORGANISER_GROUP)
    if request.method == "POST":
        form = ParticipantForm(request.POST, instance=participant)
        if form.is_valid():
            form.save()
            if request.POST.get("is_organiser"):
                participant.user.groups.add(group)
            else:
                participant.user.groups.remove(group)
            messages.success(request, "Participant saved.")
            return redirect("manage:participants")
    else:
        form = ParticipantForm(instance=participant)
    return render(
        request,
        "competition/manage/participant_form.html",
        {
            "form": form,
            "participant": participant,
            "is_organiser": participant.user.groups.filter(
                name=ORGANISER_GROUP
            ).exists(),
        },
    )


# --- seasons -----------------------------------------------------------------


@organiser_required
def seasons(request):
    return render(
        request,
        "competition/manage/seasons.html",
        {"seasons": Season.objects.all()},
    )


@organiser_required
def season_new(request):
    return _modelform(request, SeasonForm, None, "New season", reverse("manage:seasons"))


@organiser_required
def season_edit(request, pk):
    season = get_object_or_404(Season, pk=pk)
    return _modelform(
        request, SeasonForm, season, f"Edit {season.name}", reverse("manage:seasons")
    )


@organiser_required
def season_activate(request, pk):
    if request.method == "POST":
        season = get_object_or_404(Season, pk=pk)
        season.is_active = True
        season.save()  # model deactivates the others
        messages.success(request, f"“{season.name}” is now the active season.")
    return redirect("manage:seasons")


@organiser_required
def season_archive(request, pk):
    if request.method == "POST":
        season = get_object_or_404(Season, pk=pk)
        season.is_active = False
        season.save(update_fields=["is_active"])
        messages.success(request, f"“{season.name}” archived.")
    return redirect("manage:seasons")
