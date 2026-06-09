"""The reconcile screen can create a brand-new player inline and assign it."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from competition.models import (
    Entry,
    GameWeek,
    Participant,
    Player,
    ScorerPick,
    Season,
)


class ReconcileCreateTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season, week_number=1, deadline=timezone.now() + timedelta(days=1)
        )
        user = User.objects.create_user("entrant@example.com", "e@e.com", "pw")
        self.participant = Participant.objects.create(
            user=user, season=self.season, display_name="Team A", join_week=1
        )
        entry = Entry.objects.create(
            participant=self.participant, game_week=self.gw, submitted_at=timezone.now()
        )
        # An unresolved pick: typed text, no Player link.
        self.pick = ScorerPick.objects.create(
            entry=entry, position=1, player=None, player_name="Ollie Watkins"
        )
        User.objects.create_superuser("admin", "a@e.com", "pw")
        self.client.force_login(User.objects.get(username="admin"))

    def _url(self):
        return reverse("manage:reconcile", args=[self.gw.id])

    def test_create_new_player_inline_and_assign(self):
        self.assertFalse(Player.objects.filter(full_name="Ollie Watkins").exists())
        resp = self.client.post(
            self._url(),
            {f"pick_{self.pick.id}": "new", f"new_club_{self.pick.id}": "Aston Villa"},
            SERVER_NAME="localhost",
        )
        self.assertEqual(resp.status_code, 302)

        player = Player.objects.get(full_name="Ollie Watkins")
        self.assertEqual(player.club, "Aston Villa")  # club captured for disambiguation
        self.pick.refresh_from_db()
        self.assertEqual(self.pick.player_id, player.id)
        self.assertFalse(self.pick.needs_review)

    def test_create_new_uses_club_parsed_from_typed_text(self):
        self.pick.player_name = "Watkins (Aston Villa)"
        self.pick.save()
        self.client.post(
            self._url(),
            {f"pick_{self.pick.id}": "new"},  # no club box -> parse from text
            SERVER_NAME="localhost",
        )
        player = Player.objects.get(full_name__iexact="Watkins")
        self.assertEqual(player.club, "Aston Villa")

    def test_admin_can_correct_the_name_before_creating(self):
        # Entrant misspelled it; admin fixes the name box.
        self.pick.player_name = "Wattkins"
        self.pick.save()
        self.client.post(
            self._url(),
            {
                f"pick_{self.pick.id}": "new",
                f"new_name_{self.pick.id}": "Ollie Watkins",
                f"new_club_{self.pick.id}": "Aston Villa",
            },
            SERVER_NAME="localhost",
        )
        self.assertFalse(Player.objects.filter(full_name="Wattkins").exists())
        player = Player.objects.get(full_name="Ollie Watkins")
        self.pick.refresh_from_db()
        self.assertEqual(self.pick.player_id, player.id)

    def test_create_new_parses_name_dash_club_format(self):
        self.pick.player_name = "Cole Palmer - Chelsea"
        self.pick.save()
        self.client.post(
            self._url(),
            {f"pick_{self.pick.id}": "new", f"new_name_{self.pick.id}": "Cole Palmer - Chelsea"},
            SERVER_NAME="localhost",
        )
        player = Player.objects.get(full_name="Cole Palmer")
        self.assertEqual(player.club, "Chelsea")
