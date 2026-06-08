"""Service layer: bridges the ORM and the pure scoring engine, and caches results.

Recompute is triggered on results change (admin finalise), never on read, so
leaderboard pages are cheap. All writes use bulk operations so a full-season
rescore over thousands of entries stays fast.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Prefetch

from . import scoring
from .models import (
    Entry,
    Fixture,
    FixtureGoal,
    GameWeek,
    Participant,
    SeasonScore,
    WeeklyScore,
)


def score_entry(
    entry: Entry, fixtures, questions, goals_by_name, goals_by_player_id=None
) -> scoring.SectionScores:
    """Compute the four section scores for one entry from prefetched data."""
    goals_by_player_id = goals_by_player_id or {}
    # Section 1 — align predictions to fixtures by fixture id.
    preds = {mp.fixture_id: (mp.pred_home, mp.pred_away) for mp in entry.match_predictions.all()}
    s1_predictions = [preds.get(f.id, (None, None)) for f in fixtures]
    s1_results = [(f.actual_home_score, f.actual_away_score) for f in fixtures]
    s1 = scoring.score_section1(s1_predictions, s1_results)

    # Section 2 — total goals.
    tgp = getattr(entry, "total_goals_prediction", None)
    predicted_total = tgp.predicted_total if tgp else None
    actual_total = sum(
        (f.actual_home_score or 0) + (f.actual_away_score or 0)
        for f in fixtures
        if f.has_result
    )
    # Only score Section 2 once every fixture has a result (otherwise the actual
    # total is incomplete and the diff would be meaningless).
    all_results_in = all(f.has_result for f in fixtures) and len(fixtures) > 0
    s2 = scoring.score_section2(predicted_total, actual_total) if all_results_in else 0

    # Section 3 — True/False.
    answers_by_q = {a.question_id: a.answer for a in entry.tf_answers.all()}
    answers = [answers_by_q.get(q.id) for q in questions]
    correct = [q.correct_answer for q in questions]
    s3 = scoring.score_section3(answers, correct)

    # Section 4 — scorers. Match by canonical Player id first (unambiguous);
    # fall back to tolerant name matching for unresolved picks.
    resolved = []
    for pick in entry.scorer_picks.all():
        if pick.player_id and pick.player_id in goals_by_player_id:
            goals = goals_by_player_id[pick.player_id]
        elif pick.player_name:
            goals = scoring._match_goals(pick.player_name, goals_by_name)
        else:
            goals = 0
        resolved.append((pick.position, goals))
    s4 = scoring.score_resolved_picks(resolved)

    return scoring.SectionScores(s1=s1, s2=s2, s3=s3, s4=s4)


def _goals_for_week(game_week: GameWeek):
    """Aggregate goalscorer counts across the week, keyed by Player id and by name."""
    goals_by_name: dict[str, int] = {}
    goals_by_player_id: dict[int, int] = {}
    for goal in FixtureGoal.objects.filter(fixture__game_week=game_week):
        goals_by_name[goal.player_name] = goals_by_name.get(goal.player_name, 0) + goal.goals
        if goal.player_id:
            goals_by_player_id[goal.player_id] = (
                goals_by_player_id.get(goal.player_id, 0) + goal.goals
            )
    return goals_by_player_id, goals_by_name


@transaction.atomic
def recompute_game_week(game_week: GameWeek) -> None:
    """Recompute and cache WeeklyScore for every participant for this week.

    Submitters get their computed score. Non-submitters (from their join week
    onward) get the week's lowest *submitted* weekly total (spec §4 non-entry
    rule). Then the season table is recomputed.
    """
    fixtures = list(game_week.fixtures.all())
    questions = list(game_week.questions.all())
    goals_by_player_id, goals_by_name = _goals_for_week(game_week)

    entries = (
        Entry.objects.filter(game_week=game_week, submitted_at__isnull=False)
        .select_related("participant", "total_goals_prediction")
        .prefetch_related("match_predictions", "tf_answers", "scorer_picks")
    )

    submitted_scores: dict[int, scoring.SectionScores] = {}
    for entry in entries:
        submitted_scores[entry.participant_id] = score_entry(
            entry, fixtures, questions, goals_by_name, goals_by_player_id
        )

    submitted_totals = [s.total for s in submitted_scores.values()]
    lowest_total = min(submitted_totals) if submitted_totals else 0

    # All participants who count toward this week (joined on or before it).
    participants = Participant.objects.filter(
        season=game_week.season, join_week__lte=game_week.week_number
    )

    existing = {
        ws.participant_id: ws
        for ws in WeeklyScore.objects.filter(game_week=game_week)
    }
    to_create, to_update = [], []

    for participant in participants:
        scores = submitted_scores.get(participant.id)
        if scores is not None:
            fields = dict(
                s1=scores.s1, s2=scores.s2, s3=scores.s3, s4=scores.s4,
                total=scores.total, is_non_entry_default=False,
            )
        else:
            # Non-entry default: lowest submitted weekly total, attributed to S1=0..S4=0
            # but with total carried so the season sum is correct.
            fields = dict(
                s1=0, s2=0, s3=0, s4=0,
                total=lowest_total, is_non_entry_default=True,
            )

        ws = existing.get(participant.id)
        if ws is None:
            to_create.append(
                WeeklyScore(participant=participant, game_week=game_week, **fields)
            )
        else:
            for k, v in fields.items():
                setattr(ws, k, v)
            to_update.append(ws)

    if to_create:
        WeeklyScore.objects.bulk_create(to_create)
    if to_update:
        WeeklyScore.objects.bulk_update(
            to_update, ["s1", "s2", "s3", "s4", "total", "is_non_entry_default"]
        )

    recompute_season(game_week.season_id)


@transaction.atomic
def recompute_season(season_id: int) -> None:
    """Recompute cached SeasonScore totals from all finalised WeeklyScores."""
    weekly = WeeklyScore.objects.filter(game_week__season_id=season_id).select_related(
        "game_week"
    )

    totals: dict[int, dict] = {}
    for ws in weekly:
        agg = totals.setdefault(ws.participant_id, {"total": 0, "s1": 0})
        agg["total"] += ws.total
        agg["s1"] += ws.s1

    # Ensure every participant has a row even with no scores yet.
    participants = Participant.objects.filter(season_id=season_id)
    existing = {
        ss.participant_id: ss
        for ss in SeasonScore.objects.filter(season_id=season_id)
    }
    to_create, to_update = [], []
    for participant in participants:
        agg = totals.get(participant.id, {"total": 0, "s1": 0})
        ss = existing.get(participant.id)
        if ss is None:
            to_create.append(
                SeasonScore(
                    participant=participant,
                    season_id=season_id,
                    total=agg["total"],
                    s1_total=agg["s1"],
                )
            )
        else:
            ss.total = agg["total"]
            ss.s1_total = agg["s1"]
            to_update.append(ss)

    if to_create:
        SeasonScore.objects.bulk_create(to_create)
    if to_update:
        SeasonScore.objects.bulk_update(to_update, ["total", "s1_total"])


# --- Leaderboard helpers (ranking with tie-breaks) ---------------------------


def weekly_leaderboard(game_week: GameWeek):
    """Ranked rows for a week: total desc, tie-break Section 1 total desc.

    Returns a list of dicts: {rank, participant, score(WeeklyScore)}.
    Ties share a rank (joint position).
    """
    rows = list(
        WeeklyScore.objects.filter(game_week=game_week)
        .select_related("participant")
        .order_by("-total", "-s1")
    )
    return _rank(rows, key=lambda r: (r.total, r.s1))


def season_leaderboard(season_id: int):
    """Ranked rows for a season: total desc, tie-break cumulative Section 1 desc."""
    rows = list(
        SeasonScore.objects.filter(season_id=season_id)
        .select_related("participant")
        .order_by("-total", "-s1_total")
    )
    return _rank(rows, key=lambda r: (r.total, r.s1_total))


def _rank(rows, key):
    """Assign joint ("1224") ranks. rows must already be sorted by `key` desc."""
    ranked = []
    prev_key = None
    prev_rank = 0
    for i, row in enumerate(rows, start=1):
        k = key(row)
        if k == prev_key:
            rank = prev_rank
        else:
            rank = i
            prev_rank = rank
            prev_key = k
        ranked.append({"rank": rank, "participant": row.participant, "score": row})
    return ranked


def weekly_winner(game_week: GameWeek):
    """The top of the weekly leaderboard (or None). May be joint at rank 1."""
    board = weekly_leaderboard(game_week)
    winners = [r for r in board if r["rank"] == 1]
    return winners or None
