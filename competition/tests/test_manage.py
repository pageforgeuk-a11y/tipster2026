"""Manage area: access gating (Organiser group / superuser) and quick actions."""

from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from competition.models import GameWeek, Season


class ManageAccessTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.url = reverse("manage:dashboard")

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(self.url, SERVER_NAME="localhost")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_plain_user_forbidden(self):
        User.objects.create_user("u@x.com", "u@x.com", "pw")
        self.client.login(username="u@x.com", password="pw")
        resp = self.client.get(self.url, SERVER_NAME="localhost")
        self.assertEqual(resp.status_code, 403)

    def test_superuser_allowed(self):
        User.objects.create_superuser("admin", "a@x.com", "pw")
        self.client.login(username="admin", password="pw")
        resp = self.client.get(self.url, SERVER_NAME="localhost")
        self.assertEqual(resp.status_code, 200)

    def test_organiser_group_member_allowed(self):
        u = User.objects.create_user("org@x.com", "org@x.com", "pw")
        u.groups.add(Group.objects.get(name="Organiser"))  # created by migration
        self.client.login(username="org@x.com", password="pw")
        resp = self.client.get(self.url, SERVER_NAME="localhost")
        self.assertEqual(resp.status_code, 200)


class ManageActionTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season,
            week_number=1,
            deadline=timezone.now() + timedelta(days=1),
            status=GameWeek.Status.DRAFT,
        )
        User.objects.create_superuser("admin", "a@x.com", "pw")
        self.client.login(username="admin", password="pw")

    def test_open_week_action(self):
        resp = self.client.post(
            reverse("manage:week_action", args=[self.gw.id]),
            {"action": "open"},
            SERVER_NAME="localhost",
        )
        self.assertRedirects(resp, reverse("manage:dashboard"))
        self.gw.refresh_from_db()
        self.assertEqual(self.gw.status, GameWeek.Status.OPEN)

    def test_finalise_week_action_rescore(self):
        resp = self.client.post(
            reverse("manage:week_action", args=[self.gw.id]),
            {"action": "finalise"},
            SERVER_NAME="localhost",
        )
        self.assertRedirects(resp, reverse("manage:dashboard"))
        self.gw.refresh_from_db()
        self.assertEqual(self.gw.status, GameWeek.Status.FINALISED)
