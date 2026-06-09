"""Results-entry and pick-reconciliation operations.

Extracted from the admin so the on-brand Manage area and any other caller share
one implementation. These functions are UI-agnostic: they take a POST QueryDict
(or a GameWeek) and mutate data; the view layer handles messages/redirects.
"""

from __future__ import annotations

from . import players as player_resolution
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


def fixture_goal_rows(game_week: GameWeek, fixtures):
    """Annotate each fixture with team options and existing goalscorer rows."""
    for fixture in fixtures:
        fixture.team_options = [fixture.home_team, fixture.away_team]
        rows = []
        for g in fixture.goals.all():
            selected = ""
            if g.player:
                label = (
                    g.player.national_team
                    if game_week.is_international
                    else g.player.club
                )
                if label in fixture.team_options:
                    selected = label
            rows.append({"goal": g, "selected_team": selected})
        fixture.goal_rows = rows
    return fixtures


def save_results(post, game_week: GameWeek, fixtures, questions) -> None:
    """Persist scores, goalscorers (resolved to Players) and T/F answers."""
    for fixture in fixtures:
        home = post.get(f"fixture_{fixture.id}_home", "").strip()
        away = post.get(f"fixture_{fixture.id}_away", "").strip()
        fixture.actual_home_score = int(home) if home.isdigit() else None
        fixture.actual_away_score = int(away) if away.isdigit() else None
        fixture.save(update_fields=["actual_home_score", "actual_away_score"])

        fixture.goals.all().delete()
        names = post.getlist(f"scorer_name_{fixture.id}")
        counts = post.getlist(f"scorer_goals_{fixture.id}")
        teams = post.getlist(f"scorer_team_{fixture.id}")
        pens = set(post.getlist(f"scorer_pen_{fixture.id}"))
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
            if not name:
                continue
            before = Player.objects.count()
            player = player_resolution.resolve_or_create(name, club=club)
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
