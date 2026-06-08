"""The optional Team lookup self-populates from fixtures but never constrains
them — fixtures stay free text (spec §7)."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from competition.models import Fixture, GameWeek, Season, Team


class TeamLookupTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season, week_number=1, deadline=timezone.now() + timedelta(days=1)
        )

    def test_saving_fixture_creates_teams(self):
        Fixture.objects.create(
            game_week=self.gw, order=1, home_team="Arsenal", away_team="Chelsea"
        )
        self.assertTrue(Team.objects.filter(name="Arsenal").exists())
        self.assertTrue(Team.objects.filter(name="Chelsea").exists())

    def test_team_dedupe_is_case_insensitive(self):
        Fixture.objects.create(
            game_week=self.gw, order=1, home_team="Arsenal", away_team="Spurs"
        )
        Fixture.objects.create(
            game_week=self.gw, order=2, home_team="arsenal", away_team="Spurs"
        )
        self.assertEqual(Team.objects.filter(name__iexact="arsenal").count(), 1)

    def test_freetext_fixture_still_allowed_for_unknown_team(self):
        # A one-off cup/lower-league team that isn't in the lookup must still save.
        f = Fixture.objects.create(
            game_week=self.gw, order=1, home_team="Raith Rovers", away_team="Ross County"
        )
        f.refresh_from_db()
        self.assertEqual(f.home_team, "Raith Rovers")
