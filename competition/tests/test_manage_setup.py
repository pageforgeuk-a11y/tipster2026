"""Manage area Phase B: creating and setting up game weeks on-site."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from competition.models import Fixture, GameWeek, Season, TrueFalseQuestion


class WeekSetupTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        User.objects.create_superuser("admin", "a@x.com", "pw")
        self.client.login(username="admin", password="pw")

    def test_create_week_redirects_to_setup(self):
        resp = self.client.post(
            reverse("manage:week_new"),
            {
                "week_number": 5,
                "title": "Opening",
                "date_range_label": "Sat–Sun",
                "deadline": "2025-08-09T14:00",
            },
            SERVER_NAME="localhost",
        )
        gw = GameWeek.objects.get(season=self.season, week_number=5)
        self.assertRedirects(resp, reverse("manage:week_setup", args=[gw.id]))
        self.assertEqual(gw.title, "Opening")
        # Stored aware; entered as UK local 14:00.
        self.assertEqual(timezone.localtime(gw.deadline).hour, 14)

    def test_setup_saves_fixtures_and_questions(self):
        gw = GameWeek.objects.create(
            season=self.season, week_number=1, deadline=timezone.now()
        )
        data = {
            "week_number": 1,
            "title": "Wk 1",
            "date_range_label": "",
            "deadline": "2025-08-09T11:30",
            "fix_1_home": "Arsenal", "fix_1_away": "Chelsea",
            "fix_2_home": "Liverpool", "fix_2_away": "Everton",
            "q_1": "A penalty is scored",
            "q_2": "A red card is shown",
        }
        resp = self.client.post(
            reverse("manage:week_setup", args=[gw.id]), data, SERVER_NAME="localhost"
        )
        self.assertRedirects(resp, reverse("manage:dashboard"))
        self.assertEqual(gw.fixtures.count(), 2)
        self.assertEqual(gw.questions.count(), 2)
        f1 = gw.fixtures.get(order=1)
        self.assertEqual((f1.home_team, f1.away_team), ("Arsenal", "Chelsea"))
        gw.refresh_from_db()
        self.assertEqual(gw.title, "Wk 1")

    def test_blank_row_deletes_existing(self):
        gw = GameWeek.objects.create(
            season=self.season, week_number=1, deadline=timezone.now()
        )
        Fixture.objects.create(game_week=gw, order=1, home_team="A", away_team="B")
        TrueFalseQuestion.objects.create(game_week=gw, order=1, text="Q")
        data = {"week_number": 1, "deadline": "2025-08-09T11:30"}  # all fixture/q rows blank
        self.client.post(
            reverse("manage:week_setup", args=[gw.id]), data, SERVER_NAME="localhost"
        )
        self.assertEqual(gw.fixtures.count(), 0)
        self.assertEqual(gw.questions.count(), 0)

    def test_plain_user_forbidden(self):
        User.objects.create_user("u@x.com", "u@x.com", "pw")
        self.client.login(username="u@x.com", password="pw")
        resp = self.client.get(reverse("manage:week_new"), SERVER_NAME="localhost")
        self.assertEqual(resp.status_code, 403)
