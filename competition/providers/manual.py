"""Manual provider: the no-op default when no feed is configured.

Everything is entered by hand on the results-entry screen, which is always the
source of truth.
"""

from __future__ import annotations

from .base import MatchResult, ResultsProvider


class ManualProvider(ResultsProvider):
    name = "manual"

    def is_configured(self) -> bool:
        return False

    def fetch_result(self, external_match_id: str) -> MatchResult | None:
        return None
