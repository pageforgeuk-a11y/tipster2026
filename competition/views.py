"""Player-facing views: dashboard, entry submit/edit, own-entry view, leaderboards.

Deadline locking is enforced server-side at submission time (spec §9). Players
never see other players' predictions (spec §6.5).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import players as player_resolution
from . import services
from .forms import EntryForm
from .models import (
    Entry,
    GameWeek,
    MatchPrediction,
    Participant,
    Player,
    ScorerPick,
    TotalGoalsPrediction,
    TrueFalseAnswer,
    WeeklyScore,
)


def _player_suggestions(game_week):
    """Labels for the scorer typeahead datalist (club, or country in intl weeks)."""
    return [
        p.label(international=game_week.is_international)
        for p in Player.objects.filter(is_active=True)
    ]


def _participant(request):
    """The logged-in user's Participant in the active season, or None."""
    return (
        Participant.objects.filter(user=request.user, season__is_active=True)
        .select_related("season")
        .first()
    )


@login_required
def dashboard(request):
    participant = _participant(request)
    if participant is None:
        return render(request, "competition/no_season.html")

    season = participant.season
    open_week = (
        GameWeek.objects.filter(season=season, status=GameWeek.Status.OPEN)
        .order_by("week_number")
        .first()
    )
    weeks = list(GameWeek.objects.filter(season=season).order_by("week_number"))
    my_entries = {e.game_week_id: e for e in Entry.objects.filter(participant=participant)}
    for w in weeks:
        w.my_entry = my_entries.get(w.id)

    return render(
        request,
        "competition/dashboard.html",
        {
            "participant": participant,
            "season": season,
            "open_week": open_week,
            "weeks": weeks,
        },
    )


@login_required
def entry(request, week_number):
    """Submit or edit the player's entry for a week (before deadline only)."""
    participant = _participant(request)
    if participant is None:
        return render(request, "competition/no_season.html")

    game_week = get_object_or_404(
        GameWeek, season=participant.season, week_number=week_number
    )
    fixtures = list(game_week.fixtures.all())
    questions = list(game_week.questions.all())

    entry_obj = Entry.objects.filter(participant=participant, game_week=game_week).first()

    # Read-only once the deadline has passed or the week isn't open.
    editable = game_week.accepts_entries

    if request.method == "POST":
        if not editable:
            messages.error(request, "The deadline has passed — this entry is locked.")
            return redirect("entry", week_number=week_number)

        form = EntryForm(request.POST, fixtures=fixtures, questions=questions)
        if form.is_valid():
            _save_entry(participant, game_week, fixtures, questions, form)
            messages.success(request, "Your predictions have been saved.")
            return redirect("entry", week_number=week_number)
    else:
        initial = (
            _initial_from_entry(entry_obj, fixtures, questions) if entry_obj else {}
        )
        form = EntryForm(initial=initial, fixtures=fixtures, questions=questions)

    return render(
        request,
        "competition/entry.html",
        {
            "game_week": game_week,
            "form": form,
            "editable": editable,
            "entry": entry_obj,
            "participant": participant,
            "player_suggestions": _player_suggestions(game_week),
        },
    )


def _initial_from_entry(entry_obj, fixtures, questions):
    initial = {}
    for mp in entry_obj.match_predictions.all():
        initial[f"fixture_{mp.fixture_id}_home"] = mp.pred_home
        initial[f"fixture_{mp.fixture_id}_away"] = mp.pred_away
    tgp = getattr(entry_obj, "total_goals_prediction", None)
    if tgp:
        initial["total_goals"] = tgp.predicted_total
    for a in entry_obj.tf_answers.all():
        if a.answer is True:
            initial[f"tf_{a.question_id}"] = "true"
        elif a.answer is False:
            initial[f"tf_{a.question_id}"] = "false"
    for p in entry_obj.scorer_picks.all():
        initial[f"scorer_{p.position}"] = p.player_name
    return initial


@transaction.atomic
def _save_entry(participant, game_week, fixtures, questions, form):
    entry_obj, _ = Entry.objects.get_or_create(
        participant=participant, game_week=game_week
    )
    entry_obj.submitted_at = timezone.now()
    entry_obj.save()

    # Section 1
    for fixture in fixtures:
        MatchPrediction.objects.update_or_create(
            entry=entry_obj,
            fixture=fixture,
            defaults={
                "pred_home": form.cleaned_data.get(f"fixture_{fixture.id}_home"),
                "pred_away": form.cleaned_data.get(f"fixture_{fixture.id}_away"),
            },
        )

    # Section 2
    TotalGoalsPrediction.objects.update_or_create(
        entry=entry_obj,
        defaults={"predicted_total": form.cleaned_data.get("total_goals")},
    )

    # Section 3
    for question in questions:
        TrueFalseAnswer.objects.update_or_create(
            entry=entry_obj,
            question=question,
            defaults={"answer": form.tf_value(question.id)},
        )

    # Section 4 — resolve each typed pick to a canonical Player where possible.
    for position in range(1, 5):
        raw = form.cleaned_data.get(f"scorer_{position}", "").strip()
        player, needs_review = (
            player_resolution.resolve_for_pick(raw) if raw else (None, False)
        )
        ScorerPick.objects.update_or_create(
            entry=entry_obj,
            position=position,
            defaults={
                "player_name": raw,
                "player": player,
                "needs_review": needs_review,
            },
        )

    return entry_obj


@login_required
def my_entry(request, week_number):
    """Read-only view of the player's own entry, with scores once finalised."""
    participant = _participant(request)
    if participant is None:
        return render(request, "competition/no_season.html")

    game_week = get_object_or_404(
        GameWeek, season=participant.season, week_number=week_number
    )
    entry_obj = Entry.objects.filter(participant=participant, game_week=game_week).first()
    weekly_score = WeeklyScore.objects.filter(
        participant=participant, game_week=game_week
    ).first()

    return render(
        request,
        "competition/my_entry.html",
        {
            "game_week": game_week,
            "entry": entry_obj,
            "weekly_score": weekly_score,
            "participant": participant,
        },
    )


@login_required
def weekly_leaderboard(request, week_number):
    participant = _participant(request)
    if participant is None:
        return render(request, "competition/no_season.html")

    game_week = get_object_or_404(
        GameWeek, season=participant.season, week_number=week_number
    )
    board = services.weekly_leaderboard(game_week)
    return render(
        request,
        "competition/leaderboard_weekly.html",
        {"game_week": game_week, "board": board, "me": participant},
    )


@login_required
def season_leaderboard(request):
    participant = _participant(request)
    if participant is None:
        return render(request, "competition/no_season.html")

    season = participant.season
    board = services.season_leaderboard(season.id)
    return render(
        request,
        "competition/leaderboard_season.html",
        {"season": season, "board": board, "me": participant},
    )
