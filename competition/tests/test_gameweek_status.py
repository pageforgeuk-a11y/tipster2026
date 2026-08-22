"""display_status reflects real marking progress, not the stored status flag."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from competition.models import (
    Fixture,
    GameWeek,
    Season,
    TrueFalseQuestion,
)


class DisplayStatusTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)

    def _week(self, *, status, past_deadline):
        offset = timedelta(days=-1) if past_deadline else timedelta(days=1)
        return GameWeek.objects.create(
            season=self.season,
            week_number=1,
            deadline=timezone.now() + offset,
            status=status,
        )

    def _mark_complete(self, gw):
        fx = Fixture.objects.create(
            game_week=gw, order=1, home_team="A", away_team="B",
            actual_home_score=1, actual_away_score=0,
        )
        TrueFalseQuestion.objects.create(game_week=gw, order=1, text="Q?", correct_answer=True)
        return fx

    def test_open_before_deadline(self):
        gw = self._week(status=GameWeek.Status.OPEN, past_deadline=False)
        self.assertEqual(gw.display_status.label, "Open")

    def test_draft(self):
        gw = self._week(status=GameWeek.Status.DRAFT, past_deadline=False)
        self.assertEqual(gw.display_status.label, "Draft")

    def test_finalised_but_not_marked_reads_in_play(self):
        # The organiser rescored mid-week; results aren't all in yet.
        gw = self._week(status=GameWeek.Status.FINALISED, past_deadline=True)
        Fixture.objects.create(game_week=gw, order=1, home_team="A", away_team="B")  # no score
        self.assertEqual(gw.display_status.label, "In play")
        self.assertEqual(gw.display_status.pill, "live")

    def test_fully_marked_and_finalised_reads_finalised(self):
        gw = self._week(status=GameWeek.Status.FINALISED, past_deadline=True)
        self._mark_complete(gw)
        self.assertEqual(gw.display_status.label, "Finalised")

    def test_fully_marked_not_yet_finalised_reads_results_in(self):
        gw = self._week(status=GameWeek.Status.RESULTS_IN, past_deadline=True)
        self._mark_complete(gw)
        self.assertEqual(gw.display_status.label, "Results in")
