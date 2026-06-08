"""ResultsProvider interface (spec §8).

A provider, given a fixture's external_match_id, returns the final score and
goalscorers, and optionally suggested True/False answers. The feed is always a
convenience — manual entry and override remain the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GoalScorer:
    player_name: str
    goals: int = 1
    is_penalty: bool = False
    minute: int | None = None
    external_player_id: str = ""  # feed id -> canonical Player match
    team: str = ""  # the player's team in this fixture (club or country)


@dataclass
class MatchResult:
    home_score: int
    away_score: int
    scorers: list[GoalScorer] = field(default_factory=list)
    # Optional best-effort suggestions for score-derivable T/F questions, keyed
    # by a stable string; the admin still confirms every answer.
    tf_suggestions: dict = field(default_factory=dict)


class ResultsProvider:
    """Base interface. Implementations live alongside this module."""

    name = "base"

    def is_configured(self) -> bool:
        """Whether the provider has what it needs (e.g. an API key) to run."""
        return False

    def fetch_result(self, external_match_id: str) -> MatchResult | None:
        """Return the result for a linked fixture, or None if unavailable."""
        raise NotImplementedError
