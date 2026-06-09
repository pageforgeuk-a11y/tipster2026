"""Leaderboard drill-downs: team-entry privacy gate, season average, season view."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from competition import services
from competition.models import (
    Entry,
    GameWeek,
    Participant,
    Season,
    SeasonScore,
    WeeklyScore,
)


class TeamEntryPrivacyTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.viewer_user = User.objects.create_user("me@example.com", "m@e.com", "pw")
        self.viewer = Participant.objects.create(
            user=self.viewer_user, season=self.season, display_name="My Team", join_week=1
        )
        other_user = User.objects.create_user("other@example.com", "o@e.com", "pw")
        self.other = Participant.objects.create(
            user=other_user, season=self.season, display_name="Their Team", join_week=1
        )
        self.client.force_login(self.viewer_user)

    def _week(self, *, past):
        when = timezone.now() + (timedelta(days=-1) if past else timedelta(days=1))
        gw = GameWeek.objects.create(season=self.season, week_number=1, deadline=when)
        Entry.objects.create(
            participant=self.other, game_week=gw, submitted_at=timezone.now()
        )
        return gw

    def test_cannot_view_other_team_before_deadline(self):
        gw = self._week(past=False)
        resp = self.client.get(
            reverse("team_entry", args=[gw.week_number, self.other.id]),
            SERVER_NAME="localhost",
        )
        self.assertRedirects(
            resp, reverse("weekly_leaderboard", args=[gw.week_number])
        )

    def test_can_view_other_team_after_deadline(self):
        gw = self._week(past=True)
        resp = self.client.get(
            reverse("team_entry", args=[gw.week_number, self.other.id]),
            SERVER_NAME="localhost",
        )
        self.assertEqual(resp.status_code, 200)

    def test_can_always_view_own_entry_even_before_deadline(self):
        gw = self._week(past=False)
        Entry.objects.create(
            participant=self.viewer, game_week=gw, submitted_at=timezone.now()
        )
        resp = self.client.get(
            reverse("team_entry", args=[gw.week_number, self.viewer.id]),
            SERVER_NAME="localhost",
        )
        self.assertEqual(resp.status_code, 200)


class SeasonAverageTests(TestCase):
    def test_average_is_total_over_weeks(self):
        season = Season.objects.create(name="S", is_active=True)
        user = User.objects.create_user("a@example.com", "a@e.com", "pw")
        p = Participant.objects.create(
            user=user, season=season, display_name="A", join_week=1
        )
        for wk, total in [(1, 10), (2, 20), (3, 30)]:
            gw = GameWeek.objects.create(
                season=season, week_number=wk, deadline=timezone.now()
            )
            WeeklyScore.objects.create(participant=p, game_week=gw, total=total)
        SeasonScore.objects.create(participant=p, season=season, total=60)

        board = services.season_leaderboard(season.id)
        row = board[0]
        self.assertEqual(row["weeks"], 3)
        self.assertEqual(row["average"], 20.0)  # 60 / 3
