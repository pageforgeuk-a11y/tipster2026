"""Results provider selection.

`get_results_provider()` returns the configured provider. With RESULTS_PROVIDER
set to "auto" it uses API-Football when a key is present, else the manual no-op.
"""

from django.conf import settings

from .apifootball import APIFootballProvider
from .base import GoalScorer, MatchResult, ResultsProvider
from .manual import ManualProvider

__all__ = [
    "GoalScorer",
    "MatchResult",
    "ResultsProvider",
    "ManualProvider",
    "APIFootballProvider",
    "get_results_provider",
]


def get_results_provider() -> ResultsProvider:
    choice = settings.RESULTS_PROVIDER
    if choice == "manual":
        return ManualProvider()
    if choice == "apifootball":
        return APIFootballProvider()
    # auto
    api = APIFootballProvider()
    return api if api.is_configured() else ManualProvider()
