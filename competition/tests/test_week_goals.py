"""The week-level goalscorer entry: a list of picked scorers, goals per player.

Replaces the old per-fixture scorer typing. The organiser marks how many goals
each *picked* player scored across the week; scoring aggregates to that total.
"""

from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


def _post(**lists):
    """Build a QueryDict with multi-valued fields, mimicking a form POST."""
    qd = QueryDict(mutable=True)
    for key, values in lists.items():
        qd.setlist(key, values)
    return qd

from competition import results_ops, services
from competition.manage_views import ORGANISER_GROUP
from competition.models import (
    Entry,
    Fixture,
    FixtureGoal,
    GameWeek,
    Participant,
    Player,
    ScorerPick,
    Season,
    TrueFalseQuestion,
    WeeklyScore,
)


class PickedScorerRowsTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season,
            week_number=1,
            deadline=timezone.now() + timedelta(days=1),
            status=GameWeek.Status.OPEN,
        )

    def _entry(self, name):
        user = User.objects.create_user(username=name, password="x")
        part = Participant.objects.create(
            user=user, season=self.season, display_name=name
        )
        return Entry.objects.create(
            participant=part, game_week=self.gw, submitted_at=timezone.now()
        )

    def test_one_row_per_distinct_picked_player(self):
        palmer = Player.objects.create(full_name="Cole Palmer", club="Chelsea")
        e1 = self._entry("a")
        e2 = self._entry("b")
        # Same resolved player picked by two people -> one row, pick_count 2.
        ScorerPick.objects.create(entry=e1, position=1, player=palmer,
                                  player_name="Cole Palmer")
        ScorerPick.objects.create(entry=e2, position=1, player=palmer,
                                  player_name="Palmer")
        # A free-text pick with no player -> its own row.
        ScorerPick.objects.create(entry=e2, position=2, player=None,
                                  player_name="Some Unknown")

        rows = results_ops.picked_scorer_rows(self.gw)
        self.assertEqual(len(rows), 2)
        by_label = {r["label"]: r for r in rows}
        self.assertEqual(by_label["Cole Palmer (Chelsea)"]["pick_count"], 2)
        self.assertEqual(str(by_label["Cole Palmer (Chelsea)"]["player_id"]),
                         str(palmer.id))
        self.assertEqual(by_label["Some Unknown"]["pick_count"], 1)
        self.assertEqual(by_label["Some Unknown"]["player_id"], "")

    def test_free_text_same_name_groups_case_insensitively(self):
        e1 = self._entry("a")
        e2 = self._entry("b")
        ScorerPick.objects.create(entry=e1, position=1, player_name="Haaland")
        ScorerPick.objects.create(entry=e2, position=1, player_name="haaland")
        rows = results_ops.picked_scorer_rows(self.gw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pick_count"], 2)

    def test_rows_prefill_existing_goals(self):
        palmer = Player.objects.create(full_name="Cole Palmer", club="Chelsea")
        e1 = self._entry("a")
        ScorerPick.objects.create(entry=e1, position=1, player=palmer,
                                  player_name="Cole Palmer")
        FixtureGoal.objects.create(game_week=self.gw, player=palmer,
                                   player_name="Cole Palmer", goals=2)
        rows = results_ops.picked_scorer_rows(self.gw)
        self.assertEqual(rows[0]["goals"], 2)

    def test_unsubmitted_picks_excluded(self):
        user = User.objects.create_user(username="draft", password="x")
        part = Participant.objects.create(
            user=user, season=self.season, display_name="draft"
        )
        entry = Entry.objects.create(
            participant=part, game_week=self.gw, submitted_at=None
        )
        ScorerPick.objects.create(entry=entry, position=1, player_name="Ghost")
        self.assertEqual(results_ops.picked_scorer_rows(self.gw), [])


class SaveWeekGoalsTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season, week_number=1,
            deadline=timezone.now() + timedelta(days=1),
        )

    def test_stores_only_scorers_with_goals(self):
        palmer = Player.objects.create(full_name="Cole Palmer", club="Chelsea")
        post = _post(
            wg_player=[str(palmer.id), ""],
            wg_name=["Cole Palmer", "Some Unknown"],
            wg_goals=["2", "0"],  # unknown scored 0 -> not stored
        )
        results_ops.save_week_goals(post, self.gw)
        goals = list(FixtureGoal.objects.filter(game_week=self.gw))
        self.assertEqual(len(goals), 1)
        self.assertEqual(goals[0].player_id, palmer.id)
        self.assertEqual(goals[0].goals, 2)
        self.assertIsNone(goals[0].fixture_id)

    def test_save_replaces_previous(self):
        FixtureGoal.objects.create(game_week=self.gw, player_name="Old", goals=3)
        results_ops.save_week_goals(
            _post(wg_player=[""], wg_name=["New"], wg_goals=["1"]), self.gw
        )
        names = list(
            FixtureGoal.objects.filter(game_week=self.gw).values_list(
                "player_name", flat=True
            )
        )
        self.assertEqual(names, ["New"])


class ResultsViewWeekGoalsTests(TestCase):
    """The results screen POST path scores Section 4 from the picked list."""

    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season, week_number=1,
            deadline=timezone.now() - timedelta(days=1),  # past deadline
            status=GameWeek.Status.LOCKED,
        )
        self.fix = Fixture.objects.create(
            game_week=self.gw, order=1, home_team="A", away_team="B"
        )
        self.q = TrueFalseQuestion.objects.create(
            game_week=self.gw, order=1, text="Q?", correct_answer=None
        )
        palmer = Player.objects.create(full_name="Cole Palmer", club="Chelsea")
        user = User.objects.create_user(username="p", password="x")
        part = Participant.objects.create(
            user=user, season=self.season, display_name="P"
        )
        entry = Entry.objects.create(
            participant=part, game_week=self.gw, submitted_at=timezone.now()
        )
        ScorerPick.objects.create(entry=entry, position=1, player=palmer,
                                  player_name="Cole Palmer")
        self.palmer = palmer
        self.part = part

        org = User.objects.create_superuser("org", "org@x.com", "pw")
        Group.objects.get_or_create(name=ORGANISER_GROUP)
        self.client.force_login(org)

    def test_finalise_scores_section4_from_list(self):
        resp = self.client.post(
            reverse("manage:results", args=[self.gw.id]),
            {
                "action": "finalise",
                f"fixture_{self.fix.id}_home": "2",
                f"fixture_{self.fix.id}_away": "1",
                "wg_player": [str(self.palmer.id)],
                "wg_name": ["Cole Palmer"],
                "wg_goals": ["2"],
                f"tf_{self.q.id}": "true",
            },
            SERVER_NAME="localhost",
        )
        self.assertRedirects(resp, reverse("manage:dashboard"))
        ws = WeeklyScore.objects.get(participant=self.part, game_week=self.gw)
        # Position 1 (4) + 1 extra goal = 5.
        self.assertEqual(ws.s4, 5)

    def test_results_screen_lists_picked_scorer(self):
        resp = self.client.get(
            reverse("manage:results", args=[self.gw.id]), SERVER_NAME="localhost"
        )
        self.assertContains(resp, "Cole Palmer (Chelsea)")
        self.assertContains(resp, "Goalscorers picked this week")
