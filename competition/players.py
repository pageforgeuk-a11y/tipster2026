"""Player identity resolution (the heart of robust Section 4 scoring).

Two sides call in here:

* Picks (player-facing): `resolve_for_pick` maps typed text -> a single Player
  when unambiguous, flags it for review when ambiguous, and leaves it unresolved
  (free text) when unknown. Never creates rows — a pick shouldn't invent people.

* Results (admin / feed): `resolve_or_create` always returns a Player, creating
  a canonical row when needed, keyed on the feed's `external_player_id` where
  available and otherwise on (name, club).

Matching is tolerant: case-insensitive, punctuation-insensitive, with a surname
fallback ("Salah" -> "Mohamed Salah") and a club hint to break ties.
"""

from __future__ import annotations

from .models import Player
from .scoring import normalize_name as _norm


def parse_label(raw: str):
    """Split a typed scorer into (name, club_hint).

    Handles both common formats people use:
      "Erling Haaland (Man City)"  -> ("Erling Haaland", "Man City")
      "Erling Haaland - Man City"  -> ("Erling Haaland", "Man City")
    A bare name returns (name, None). The club hint comes from the typeahead
    label or, on the results side, the fixture's teams.
    """
    raw = (raw or "").strip()
    if raw.endswith(")") and "(" in raw:
        i = raw.rfind("(")
        return raw[:i].strip(), raw[i + 1 : -1].strip()
    # " - " (spaces around the dash) separates name from club; safe against
    # hyphenated names like "Pierre-Emerick Aubameyang" (no surrounding spaces).
    if " - " in raw:
        name, club = raw.split(" - ", 1)
        return name.strip(), club.strip()
    return raw, None


def _candidates(name, club_hint=None, active_only=True):
    """Players matching `name`, narrowed by `club_hint` when it disambiguates."""
    target = _norm(name)
    if not target:
        return []

    qs = Player.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    pool = list(qs)

    exact = [p for p in pool if _norm(p.full_name) == target]
    matches = exact
    if not matches and " " not in target:
        # Surname fallback: bare token equals the last token of a full name.
        matches = [p for p in pool if _norm(p.full_name).split()[-1:] == [target]]

    if club_hint and len(matches) > 1:
        ch = _norm(club_hint)
        narrowed = [
            p for p in matches if _norm(p.club) == ch or _norm(p.national_team) == ch
        ]
        if narrowed:
            matches = narrowed

    return matches


def resolve_for_pick(raw: str):
    """Map a pick's raw text to (player_or_None, needs_review).

    * exactly one match  -> (player, False)
    * no match           -> (None, False)   # unknown, kept as free text
    * many matches       -> (None, True)    # ambiguous, admin must reconcile
    """
    name, club = parse_label(raw)
    if not name:
        return None, False
    matches = _candidates(name, club_hint=club, active_only=True)
    if len(matches) == 1:
        return matches[0], False
    if not matches:
        return None, False
    return None, True


def resolve_or_create(name, club=None, national_team=None, external_player_id=None):
    """Return a canonical Player for a goalscorer, creating one if needed.

    Tolerates a labelled name like "Danny Welbeck (Brighton)" or
    "Danny Welbeck - Brighton": the club is split off the name (so we don't
    create a player literally called "Danny Welbeck (Brighton)") and used as the
    club hint when none was passed explicitly.
    """
    parsed_name, parsed_club = parse_label(name or "")
    name = parsed_name.strip()
    club = (club or "").strip()
    national_team = (national_team or "").strip()
    external_player_id = (external_player_id or "").strip()
    # Fall back to the club parsed out of the label only when the caller didn't
    # already give us a club or national team to use.
    if not club and not national_team and parsed_club:
        club = parsed_club

    if external_player_id:
        existing = Player.objects.filter(
            external_player_id=external_player_id
        ).first()
        if existing:
            _backfill(existing, club, national_team)
            return existing

    matches = _candidates(name, club_hint=club, active_only=False)
    if len(matches) == 1:
        player = matches[0]
        _backfill(player, club, national_team, external_player_id)
        return player

    # Zero matches, or ambiguous without a usable club hint: create a distinct
    # row (the club label keeps future matches unambiguous).
    return Player.objects.create(
        full_name=name,
        club=club,
        national_team=national_team,
        external_player_id=external_player_id,
    )


def _backfill(player, club="", national_team="", external_player_id=""):
    """Fill in blanks on an existing Player from fresh feed/admin data."""
    changed = []
    if club and not player.club:
        player.club = club
        changed.append("club")
    if national_team and not player.national_team:
        player.national_team = national_team
        changed.append("national_team")
    if external_player_id and not player.external_player_id:
        player.external_player_id = external_player_id
        changed.append("external_player_id")
    if changed:
        player.save(update_fields=changed)


def merge_players(primary: Player, duplicates) -> int:
    """Repoint all picks/goals from `duplicates` onto `primary`, then delete them.

    Returns the number of duplicates merged. Used by the admin merge action to
    tidy the self-populated list.
    """
    from .models import FixtureGoal, ScorerPick

    count = 0
    for dup in duplicates:
        if dup.pk == primary.pk:
            continue
        ScorerPick.objects.filter(player=dup).update(player=primary)
        FixtureGoal.objects.filter(player=dup).update(player=primary)
        _backfill(primary, dup.club, dup.national_team, dup.external_player_id)
        dup.delete()
        count += 1
    return count
