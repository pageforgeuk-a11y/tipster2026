"""Pure, re-runnable scoring engine (spec §4).

Nothing in this module touches the database. Every function takes plain Python
data and returns plain Python data, so the rules are exhaustively unit-testable
and a batch rescore over thousands of entries is fast and deterministic.

The model/service layer (competition.services) is responsible for turning ORM
objects into these primitives and caching the results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# --- Section 1: match result & exact score -----------------------------------

# Outcome points keyed by the *actual* outcome, awarded only when the prediction
# matches that outcome.
_OUTCOME_POINTS = {"home": 3, "draw": 4, "away": 5}


def _outcome(home: int, away: int) -> str:
    if home > away:
        return "home"
    if home < away:
        return "away"
    return "draw"


def score_fixture(pred_home, pred_away, act_home, act_away) -> int:
    """Points for a single fixture: outcome points + exact-score bonus (they stack).

    Returns 0 if the result or the prediction is missing.
    """
    if act_home is None or act_away is None:
        return 0
    if pred_home is None or pred_away is None:
        return 0

    points = 0
    if _outcome(pred_home, pred_away) == _outcome(act_home, act_away):
        points += _OUTCOME_POINTS[_outcome(act_home, act_away)]

    if pred_home == act_home and pred_away == act_away:
        combined = act_home + act_away
        points += 5 if combined <= 4 else 7

    return points


def score_section1(predictions, results) -> int:
    """Sum over fixtures.

    predictions: iterable of (pred_home, pred_away)
    results:     iterable of (act_home, act_away)  (aligned by fixture order)
    """
    total = 0
    for (ph, pa), (ah, aa) in zip(predictions, results):
        total += score_fixture(ph, pa, ah, aa)
    return total


# --- Section 2: total goals across all 10 matches ----------------------------

_TOTAL_GOALS_POINTS = {0: 5, 1: 3, 2: 2, 3: 1}


def score_section2(predicted_total, actual_total) -> int:
    if predicted_total is None or actual_total is None:
        return 0
    diff = abs(predicted_total - actual_total)
    return _TOTAL_GOALS_POINTS.get(diff, 0)


# --- Section 3: True/False (8 questions) --------------------------------------


def score_section3(answers, correct) -> int:
    """+2 per correct answer, +4 bonus if all (and there are 8) are correct. Max 20.

    answers: iterable of bool|None (player answers)
    correct: iterable of bool|None (admin-set correct answers)
    """
    answers = list(answers)
    correct = list(correct)

    points = 0
    correct_count = 0
    gradable = 0  # questions with a known correct answer
    for a, c in zip(answers, correct):
        if c is None:
            continue  # not yet graded -> cannot contribute or complete the sweep
        gradable += 1
        if a is not None and a == c:
            points += 2
            correct_count += 1

    # All-correct bonus only when all 8 are graded and all 8 are right.
    if len(correct) == 8 and gradable == 8 and correct_count == 8:
        points += 4

    return points


# --- Section 4: predict the scorers (4 ranked picks) -------------------------

_POSITION_VALUE = {1: 4, 2: 3, 3: 2, 4: 1}


def normalize_name(name: str) -> str:
    """Lowercase, strip accents-as-written, collapse whitespace and punctuation."""
    if not name:
        return ""
    name = name.strip().lower()
    name = re.sub(r"[.\-']", " ", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def _match_goals(pick_name: str, goals_by_name: dict) -> int:
    """Goals scored by the picked player, tolerant to name formatting.

    goals_by_name maps a player name -> total goals across the week's fixtures.
    Matching: normalised exact match first, then a surname (last-token) match so
    "Haaland" matches "Erling Haaland". Returns 0 if no confident match.
    """
    target = normalize_name(pick_name)
    if not target:
        return 0

    normalized = {}
    for raw, g in goals_by_name.items():
        normalized[normalize_name(raw)] = normalized.get(normalize_name(raw), 0) + g

    if target in normalized:
        return normalized[target]

    # Surname fallback: the pick is a single token that equals the last token of
    # exactly one scorer's full name.
    if " " not in target:
        candidates = {
            full: g for full, g in normalized.items() if full.split()[-1:] == [target]
        }
        if len(candidates) == 1:
            return next(iter(candidates.values()))

    return 0


def position_points(position, goals) -> int:
    """Points for one resolved pick: position value + 1 per goal beyond the first.

    Returns 0 if the player did not score. This is the pure core; the service
    layer decides how many goals a pick scored (by Player id, name fallback).
    """
    if not goals or goals < 1:
        return 0
    return _POSITION_VALUE[position] + (goals - 1)


def score_resolved_picks(resolved) -> int:
    """Sum points for picks already resolved to goal counts.

    resolved: iterable of (position, goals)
    """
    return sum(position_points(position, goals) for position, goals in resolved)


def score_section4(picks, goals_by_name) -> int:
    """Name-based Section 4 scoring (fallback path + the pure name-match tests).

    picks: iterable of (position, player_name)
    goals_by_name: dict of player_name -> goals across the week
    """
    total = 0
    for position, name in picks:
        if not name:
            continue
        total += position_points(position, _match_goals(name, goals_by_name))
    return total


# --- Aggregation -------------------------------------------------------------


@dataclass(frozen=True)
class SectionScores:
    s1: int = 0
    s2: int = 0
    s3: int = 0
    s4: int = 0

    @property
    def total(self) -> int:
        return self.s1 + self.s2 + self.s3 + self.s4
