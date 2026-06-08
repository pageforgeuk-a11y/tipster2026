"""API-Football provider (free tier, ~100 req/day — ample for ~10 matches/week).

Docs: https://www.api-football.com/documentation-v3
Auth: the `x-apisports.io` style key passed as the `x-apisports-key` header.

Only ever a convenience: if the network call fails or the key is missing, the
admin enters results by hand. The key lives in env vars.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from .base import GoalScorer, MatchResult, ResultsProvider

logger = logging.getLogger(__name__)


class APIFootballProvider(ResultsProvider):
    name = "apifootball"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key if api_key is not None else settings.APIFOOTBALL_API_KEY
        self.base_url = (base_url or settings.APIFOOTBALL_BASE_URL).rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self):
        return {"x-apisports-key": self.api_key}

    def fetch_result(self, external_match_id: str) -> MatchResult | None:
        if not self.is_configured() or not external_match_id:
            return None
        try:
            fixture = self._get_fixture(external_match_id)
            if fixture is None:
                return None
            scorers = self._get_scorers(external_match_id)
            return MatchResult(
                home_score=fixture["home"],
                away_score=fixture["away"],
                scorers=scorers,
            )
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            logger.warning("API-Football fetch failed for %s: %s", external_match_id, exc)
            return None

    def _get_fixture(self, match_id):
        resp = requests.get(
            f"{self.base_url}/fixtures",
            headers=self._headers(),
            params={"id": match_id},
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("response", [])
        if not items:
            return None
        goals = items[0].get("goals", {})
        if goals.get("home") is None or goals.get("away") is None:
            return None  # not finished yet
        return {"home": int(goals["home"]), "away": int(goals["away"])}

    def _get_scorers(self, match_id) -> list[GoalScorer]:
        resp = requests.get(
            f"{self.base_url}/fixtures/events",
            headers=self._headers(),
            params={"fixture": match_id},
            timeout=10,
        )
        resp.raise_for_status()
        counts: dict[str, GoalScorer] = {}
        for event in resp.json().get("response", []):
            if event.get("type") != "Goal":
                continue
            detail = (event.get("detail") or "").lower()
            if detail in ("missed penalty", "own goal"):
                continue  # own goals/missed pens don't credit the picked scorer
            player = event.get("player") or {}
            name = player.get("name")
            if not name:
                continue
            # Key on the feed's player id when present so two same-named players
            # stay distinct; fall back to name.
            pid = str(player.get("id") or "")
            key = pid or name
            is_pen = detail == "penalty"
            team = (event.get("team") or {}).get("name", "")
            if key in counts:
                counts[key].goals += 1
                counts[key].is_penalty = counts[key].is_penalty or is_pen
            else:
                counts[key] = GoalScorer(
                    player_name=name,
                    goals=1,
                    is_penalty=is_pen,
                    external_player_id=pid,
                    team=team,
                )
        return list(counts.values())
