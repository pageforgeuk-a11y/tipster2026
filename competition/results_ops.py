"""Results-entry and pick-reconciliation operations.

Extracted from the admin so the on-brand Manage area and any other caller share
one implementation. These functions are UI-agnostic: they take a POST QueryDict
(or a GameWeek) and mutate data; the view layer handles messages/redirects.
"""

from __future__ import annotations

from . import players as player_resolution
from . import scoring
from .models import FixtureGoal, GameWeek, Player, ScorerPick
from .providers import get_results_provider


def player_labels(game_week: GameWeek):
    """Scorer typeahead labels — club, or national team in international weeks."""
    return [
        p.label(international=game_week.is_international)
        for p in Player.objects.filter(is_active=True)
    ]


def unresolved_picks(game_week: GameWeek):
    """Submitted picks for the week with text but no confident Player link."""
    return ScorerPick.objects.filter(
        entry__game_week=game_week,
        entry__submitted_at__isnull=False,
        player__isnull=True,
    ).exclude(player_name="")


def reresolve_picks(game_week: GameWeek) -> None:
    """Re-run pick resolution — new players from results may now match picks."""
    for pick in ScorerPick.objects.filter(
        entry__game_week=game_week, player__isnull=True
    ).exclude(player_name=""):
        player, needs_review = player_resolution.resolve_for_pick(pick.player_name)
        if player or needs_review != pick.needs_review:
            pick.player = player
            pick.needs_review = needs_review
            pick.save(update_fields=["player", "needs_review"])


def picked_scorer_rows(game_week: GameWeek):
    """The distinct scorers picked across the week, each with its goal tally.

    This is what the organiser marks on the results screen: one row per player
    that appears in any submitted entry's scorer picks, pre-filled with any goals
    already recorded for the week. Rows are grouped by resolved Player where
    known, otherwise by normalised name, so the same person shows only once.
    """
    goals_by_pid: dict[int, int] = {}
    goals_by_norm: dict[str, int] = {}
    for g in FixtureGoal.objects.filter(game_week=game_week):
        if g.player_id:
            goals_by_pid[g.player_id] = goals_by_pid.get(g.player_id, 0) + g.goals
        else:
            key = scoring.normalize_name(g.player_name)
            goals_by_norm[key] = goals_by_norm.get(key, 0) + g.goals

    picks = ScorerPick.objects.filter(
        entry__game_week=game_week,
        entry__submitted_at__isnull=False,
    ).select_related("player")

    groups: dict[tuple, dict] = {}
    for pick in picks:
        if pick.player_id:
            key = ("p", pick.player_id)
            label = pick.player.label(international=game_week.is_international)
            player_id, name = pick.player_id, pick.player.full_name
        else:
            name = (pick.player_name or "").strip()
            if not name:
                continue
            key = ("n", scoring.normalize_name(name))
            label, player_id = name, ""
        row = groups.get(key)
        if row is None:
            row = groups[key] = {
                "player_id": player_id,
                "name": name,
                "label": label,
                "pick_count": 0,
                "needs_review": False,
                "goals": 0,
            }
        row["pick_count"] += 1
        row["needs_review"] = row["needs_review"] or pick.needs_review

    for (kind, kid), row in groups.items():
        row["goals"] = (goals_by_pid if kind == "p" else goals_by_norm).get(kid, 0)

    return sorted(groups.values(), key=lambda r: r["label"].lower())


def save_week_goals(post, game_week: GameWeek) -> None:
    """Replace the week's goal tallies from the picked-scorers list.

    The list carries a hidden player id and name per row (see
    picked_scorer_rows); a row is stored only when its goal count is 1+.
    """
    player_ids = post.getlist("wg_player")
    names = post.getlist("wg_name")
    counts = post.getlist("wg_goals")

    FixtureGoal.objects.filter(game_week=game_week).delete()
    to_create = []
    for idx, raw in enumerate(counts):
        raw = raw.strip()
        goals = int(raw) if raw.isdigit() else 0
        if goals < 1:
            continue
        pid = player_ids[idx].strip() if idx < len(player_ids) else ""
        name = names[idx].strip() if idx < len(names) else ""
        player = Player.objects.filter(pk=pid).first() if pid.isdigit() else None
        to_create.append(
            FixtureGoal(
                game_week=game_week,
                fixture=None,
                player=player,
                player_name=name or (player.full_name if player else ""),
                goals=goals,
            )
        )
    if to_create:
        FixtureGoal.objects.bulk_create(to_create)


def save_results(post, game_week: GameWeek, fixtures, questions) -> None:
    """Persist match scores, week goal tallies and T/F answers."""
    for fixture in fixtures:
        home = post.get(f"fixture_{fixture.id}_home", "").strip()
        away = post.get(f"fixture_{fixture.id}_away", "").strip()
        fixture.actual_home_score = int(home) if home.isdigit() else None
        fixture.actual_away_score = int(away) if away.isdigit() else None
        fixture.save(update_fields=["actual_home_score", "actual_away_score"])

    save_week_goals(post, game_week)

    for question in questions:
        val = post.get(f"tf_{question.id}", "")
        if val == "true":
            question.correct_answer = True
        elif val == "false":
            question.correct_answer = False
        else:
            question.correct_answer = None
        question.save(update_fields=["correct_answer"])


def autofill(game_week: GameWeek, fixtures) -> dict:
    """Pull scores/scorers from the results provider for linked fixtures.

    Returns {configured, provider_name, filled}. Never raises.
    """
    provider = get_results_provider()
    if not provider.is_configured():
        return {"configured": False, "provider_name": provider.name, "filled": 0}

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
    reresolve_picks(game_week)
    return {"configured": True, "provider_name": provider.name, "filled": filled}


def reconcile_rows(game_week: GameWeek):
    """Rows for the reconcile screen: each unresolved pick + likely matches."""
    rows = []
    for pick in unresolved_picks(game_week).select_related("entry__participant"):
        suggestions = player_resolution._candidates(
            player_resolution.parse_label(pick.player_name)[0], active_only=True
        )
        rows.append({"pick": pick, "suggestions": suggestions})
    return rows


def apply_reconcile(post, game_week: GameWeek) -> tuple[int, int]:
    """Apply reconcile choices. Returns (picks_updated, players_created)."""
    updated = created = 0
    for pick in unresolved_picks(game_week):
        raw = post.get(f"pick_{pick.id}", "").strip()
        if not raw:
            continue
        if raw == "new":
            typed = post.get(f"new_name_{pick.id}", "").strip() or pick.player_name
            name, club_from_text = player_resolution.parse_label(typed)
            club = post.get(f"new_club_{pick.id}", "").strip() or club_from_text
            national_team = post.get(f"new_natteam_{pick.id}", "").strip()
            if not name:
                continue
            before = Player.objects.count()
            player = player_resolution.resolve_or_create(
                name, club=club, national_team=national_team
            )
            if Player.objects.count() > before:
                created += 1
        else:
            player = Player.objects.filter(pk=raw).first() if raw.isdigit() else None
        if player:
            pick.player = player
            pick.needs_review = False
            pick.save(update_fields=["player", "needs_review"])
            updated += 1
    return updated, created
