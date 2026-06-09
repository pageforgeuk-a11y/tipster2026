"""Manage area Phase C: management lists, merge, organiser toggle, seasons."""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from competition.models import (
    FixtureGoal,
    Participant,
    Player,
    QuestionTemplate,
    Season,
    Team,
)


class ManageListsTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="2025-26", is_active=True)
        User.objects.create_superuser("admin", "a@x.com", "pw")
        self.client.login(username="admin", password="pw")

    def test_list_pages_load(self):
        for name in ("players", "teams", "questions", "participants", "seasons"):
            resp = self.client.get(reverse(f"manage:{name}"), SERVER_NAME="localhost")
            self.assertEqual(resp.status_code, 200, name)

    def test_plain_user_forbidden(self):
        User.objects.create_user("u@x.com", "u@x.com", "pw")
        self.client.login(username="u@x.com", password="pw")
        resp = self.client.get(reverse("manage:players"), SERVER_NAME="localhost")
        self.assertEqual(resp.status_code, 403)

    def test_add_team_and_question(self):
        self.client.post(
            reverse("manage:team_new"),
            {"name": "Arsenal", "short_name": "ARS", "is_active": "on"},
            SERVER_NAME="localhost",
        )
        self.assertTrue(Team.objects.filter(name="Arsenal").exists())
        self.client.post(
            reverse("manage:question_new"),
            {"text": "A penalty is scored", "is_active": "on"},
            SERVER_NAME="localhost",
        )
        self.assertTrue(QuestionTemplate.objects.filter(text="A penalty is scored").exists())

    def test_player_merge(self):
        keep = Player.objects.create(full_name="Tommy Smith", club="Everton")
        dupe = Player.objects.create(full_name="Tommy Smith", club="")
        # a goal pointing at the duplicate should move to the kept player
        from competition.models import Fixture, GameWeek
        gw = GameWeek.objects.create(season=self.season, week_number=1, deadline="2025-01-01T00:00:00Z")
        fx = Fixture.objects.create(game_week=gw, order=1, home_team="A", away_team="B")
        FixtureGoal.objects.create(fixture=fx, player=dupe, player_name="Smith", goals=1)

        resp = self.client.post(
            reverse("manage:players_merge"),
            {"ids": [keep.id, dupe.id]},
            SERVER_NAME="localhost",
        )
        self.assertRedirects(resp, reverse("manage:players"))
        self.assertFalse(Player.objects.filter(id=dupe.id).exists())
        self.assertEqual(FixtureGoal.objects.get().player_id, keep.id)

    def test_organiser_toggle(self):
        user = User.objects.create_user("p@x.com", "p@x.com", "pw")
        part = Participant.objects.create(
            user=user, season=self.season, display_name="Team P", join_week=1
        )
        # Grant organiser
        self.client.post(
            reverse("manage:participant_edit", args=[part.id]),
            {"display_name": "Team P", "join_week": 1, "is_organiser": "on"},
            SERVER_NAME="localhost",
        )
        self.assertTrue(user.groups.filter(name="Organiser").exists())
        # Revoke
        self.client.post(
            reverse("manage:participant_edit", args=[part.id]),
            {"display_name": "Team P", "join_week": 1},
            SERVER_NAME="localhost",
        )
        self.assertFalse(user.groups.filter(name="Organiser").exists())


class SeasonManageTests(TestCase):
    def setUp(self):
        User.objects.create_superuser("admin", "a@x.com", "pw")
        self.client.login(username="admin", password="pw")

    def test_create_and_activate_archives_others(self):
        old = Season.objects.create(name="Old", is_active=True)
        new = Season.objects.create(name="New", is_active=False)
        self.client.post(
            reverse("manage:season_activate", args=[new.id]), SERVER_NAME="localhost"
        )
        old.refresh_from_db()
        new.refresh_from_db()
        self.assertTrue(new.is_active)
        self.assertFalse(old.is_active)  # only one active at a time
