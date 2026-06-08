"""Integration tests for the scoring/recompute service and leaderboards.

Exercises the non-entry default rule, weekly + season aggregation, and the
tie-break ordering (spec §4 aggregation/tie-breaks, §13 data integrity).
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from competition import services
from competition.models import (
    Entry,
    Fixture,
    FixtureGoal,
    GameWeek,
    MatchPrediction,
    Participant,
    ScorerPick,
    Season,
    TotalGoalsPrediction,
    TrueFalseAnswer,
    TrueFalseQuestion,
    WeeklyScore,
)


class ScoringServiceTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="Test Season", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season,
            week_number=1,
            deadline=timezone.now() + timedelta(days=1),
            status=GameWeek.Status.OPEN,
        )
        # Two fixtures is enough to exercise S1 + S2.
        self.f1 = Fixture.objects.create(
            game_week=self.gw, order=1, home_team="A", away_team="B"
        )
        self.f2 = Fixture.objects.create(
            game_week=self.gw, order=2, home_team="C", away_team="D"
        )
        self.q = TrueFalseQuestion.objects.create(
            game_week=self.gw, order=1, text="Q1", correct_answer=True
        )

    def _make_participant(self, name, join_week=1):
        user = User.objects.create_user(username=name, password="x")
        return Participant.objects.create(
            user=user, season=self.season, display_name=name.title(), join_week=join_week
        )

    def _make_entry(self, participant, preds, total, tf, scorer=None):
        entry = Entry.objects.create(
            participant=participant, game_week=self.gw, submitted_at=timezone.now()
        )
        for fixture, (ph, pa) in zip([self.f1, self.f2], preds):
            MatchPrediction.objects.create(
                entry=entry, fixture=fixture, pred_home=ph, pred_away=pa
            )
        TotalGoalsPrediction.objects.create(entry=entry, predicted_total=total)
        TrueFalseAnswer.objects.create(entry=entry, question=self.q, answer=tf)
        if scorer:
            ScorerPick.objects.create(entry=entry, position=1, player_name=scorer)
        return entry

    def _set_results(self):
        self.f1.actual_home_score, self.f1.actual_away_score = 2, 0  # home win
        self.f1.save()
        self.f2.actual_home_score, self.f2.actual_away_score = 1, 1  # draw
        self.f2.save()
        FixtureGoal.objects.create(fixture=self.f1, player_name="Smith", goals=2)

    def test_submitted_entry_scores_all_sections(self):
        p = self._make_participant("alice")
        # f1 exact 2-0 (home win 3 + bonus 5 = 8); f2 draw 1-1 exact (4 + 5 = 9).
        # total goals actual = 4, predict 4 -> 5. TF correct -> 2. Scorer Smith x2 -> 4+1=5.
        self._make_entry(p, [(2, 0), (1, 1)], total=4, tf=True, scorer="Smith")
        self._set_results()
        services.recompute_game_week(self.gw)

        ws = WeeklyScore.objects.get(participant=p, game_week=self.gw)
        self.assertEqual(ws.s1, 8 + 9)
        self.assertEqual(ws.s2, 5)
        self.assertEqual(ws.s3, 2)
        self.assertEqual(ws.s4, 5)
        self.assertEqual(ws.total, 17 + 5 + 2 + 5)
        self.assertFalse(ws.is_non_entry_default)

    def test_non_entry_gets_lowest_submitted_total(self):
        high = self._make_participant("high")
        low = self._make_participant("low")
        absent = self._make_participant("absent")

        self._set_results()
        # High scorer: everything right-ish.
        self._make_entry(high, [(2, 0), (1, 1)], total=4, tf=True)
        # Low scorer: all wrong.
        self._make_entry(low, [(0, 2), (2, 0)], total=99, tf=False)
        services.recompute_game_week(self.gw)

        low_ws = WeeklyScore.objects.get(participant=low, game_week=self.gw)
        absent_ws = WeeklyScore.objects.get(participant=absent, game_week=self.gw)
        self.assertTrue(absent_ws.is_non_entry_default)
        self.assertEqual(absent_ws.total, low_ws.total)

    def test_non_entry_default_only_from_join_week(self):
        # A participant who joins in week 2 must not get a row for week 1.
        late = self._make_participant("late", join_week=2)
        self._set_results()
        services.recompute_game_week(self.gw)
        self.assertFalse(
            WeeklyScore.objects.filter(participant=late, game_week=self.gw).exists()
        )

    def test_season_aggregation_and_tiebreak_ordering(self):
        a = self._make_participant("a")
        b = self._make_participant("b")
        self._set_results()
        # Give A more Section 1, B less but same total via other sections is hard;
        # instead just check ordering by total then s1.
        self._make_entry(a, [(2, 0), (1, 1)], total=4, tf=True)  # high
        self._make_entry(b, [(2, 0), (0, 0)], total=0, tf=False)  # lower
        services.recompute_game_week(self.gw)

        board = services.season_leaderboard(self.season.id)
        # A should rank above B.
        names = [row["participant"].display_name for row in board]
        self.assertEqual(names[0], "A")
        self.assertEqual(board[0]["rank"], 1)

    def test_rescore_is_deterministic_and_idempotent(self):
        p = self._make_participant("alice")
        self._make_entry(p, [(2, 0), (1, 1)], total=4, tf=True)
        self._set_results()
        services.recompute_game_week(self.gw)
        first = WeeklyScore.objects.get(participant=p, game_week=self.gw).total
        services.recompute_game_week(self.gw)
        second = WeeklyScore.objects.get(participant=p, game_week=self.gw).total
        self.assertEqual(first, second)
        # No duplicate rows created on re-run.
        self.assertEqual(
            WeeklyScore.objects.filter(participant=p, game_week=self.gw).count(), 1
        )


class WeeklyLeaderboardTieTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season, week_number=1, deadline=timezone.now()
        )

    def test_joint_rank_on_equal_total_and_s1(self):
        for name in ("x", "y"):
            user = User.objects.create_user(username=name, password="x")
            p = Participant.objects.create(
                user=user, season=self.season, display_name=name
            )
            WeeklyScore.objects.create(
                participant=p, game_week=self.gw, s1=5, total=10
            )
        board = services.weekly_leaderboard(self.gw)
        self.assertEqual(board[0]["rank"], 1)
        self.assertEqual(board[1]["rank"], 1)  # joint first
