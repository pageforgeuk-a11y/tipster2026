"""Player-facing views: dashboard, entry submit/edit, own-entry view, leaderboards.

Deadline locking is enforced server-side at submission time (spec §9). Players
never see other players' predictions (spec §6.5).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
    SeasonScore,
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


def _entry_detail(request, viewer, subject, game_week, back_url):
    """Render the per-item breakdown for `subject`'s entry, viewed by `viewer`."""
    entry_obj = Entry.objects.filter(participant=subject, game_week=game_week).first()
    weekly_score = WeeklyScore.objects.filter(
        participant=subject, game_week=game_week
    ).first()
    breakdown = services.entry_breakdown(entry_obj, game_week) if entry_obj else None
    return render(
        request,
        "competition/my_entry.html",
        {
            "game_week": game_week,
            "entry": entry_obj,
            "weekly_score": weekly_score,
            "breakdown": breakdown,
            "participant": viewer,
            "subject": subject,
            "is_self": subject.id == viewer.id,
            "back_url": back_url,
        },
    )


@login_required
def my_entry(request, week_number):
    """Read-only view of the player's own entry, with scores once finalised."""
    participant = _participant(request)
    if participant is None:
        return render(request, "competition/no_season.html")

    game_week = get_object_or_404(
        GameWeek, season=participant.season, week_number=week_number
    )

    return _entry_detail(
        request, participant, participant, game_week, reverse("dashboard")
    )


@login_required
def team_entry(request, week_number, participant_id):
    """View a given team's entry for a week.

    Own entry is always viewable; another team's predictions only after the
    deadline has passed (so it can't be used to copy before the deadline).
    """
    viewer = _participant(request)
    if viewer is None:
        return render(request, "competition/no_season.html")

    game_week = get_object_or_404(
        GameWeek, season=viewer.season, week_number=week_number
    )
    subject = get_object_or_404(Participant, id=participant_id, season=viewer.season)

    if subject.id != viewer.id and not game_week.is_past_deadline:
        messages.error(
            request,
            "You can only view another team's predictions after the deadline has passed.",
        )
        return redirect("weekly_leaderboard", week_number=week_number)


    return _entry_detail(
        request,
        viewer,
        subject,
        game_week,
        reverse("weekly_leaderboard", args=[week_number]),
    )


@login_required
def season_team(request, participant_id):
    """Drill-down: a team's weekly scores across the season (totals are public)."""
    viewer = _participant(request)
    if viewer is None:
        return render(request, "competition/no_season.html")

    subject = get_object_or_404(Participant, id=participant_id, season=viewer.season)
    weekly = list(
        WeeklyScore.objects.filter(
            participant=subject, game_week__season=viewer.season
        )
        .select_related("game_week")
        .order_by("game_week__week_number")
    )
    season_score = SeasonScore.objects.filter(
        participant=subject, season=viewer.season
    ).first()
    weeks = len(weekly)
    total = season_score.total if season_score else 0
    average = round(total / weeks, 1) if weeks else 0

    return render(
        request,
        "competition/season_team.html",
        {
            "subject": subject,
            "weekly": weekly,
            "total": total,
            "average": average,
            "weeks": weeks,
            "me": viewer,
            "is_self": subject.id == viewer.id,
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
