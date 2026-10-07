"""Home page 'All game weeks' list: newest first, five at a time."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from competition.models import GameWeek, Participant, Season


class HomeWeekListTests(TestCase):
    def setUp(self):
        season = Season.objects.create(name="S", is_active=True)
        for n in range(1, 8):  # GW1..GW7
            GameWeek.objects.create(
                season=season, week_number=n,
                deadline=timezone.now() + timedelta(days=n),
            )
        user = User.objects.create_user("p@x.com", "p@x.com", "pw")
        Participant.objects.create(user=user, season=season, display_name="P")
        self.client.force_login(user)

    def test_newest_first_five_at_a_time(self):
        resp = self.client.get(reverse("dashboard"), SERVER_NAME="localhost")
        self.assertEqual([w.week_number for w in resp.context["weeks"]], [7, 6, 5, 4, 3])
        self.assertContains(resp, "?show=10#weeks")
        self.assertContains(resp, "Show 2 more")

    def test_show_more_reveals_older_weeks(self):
        resp = self.client.get(reverse("dashboard") + "?show=10", SERVER_NAME="localhost")
        self.assertEqual(
            [w.week_number for w in resp.context["weeks"]], [7, 6, 5, 4, 3, 2, 1]
        )
        self.assertNotContains(resp, "older week")
