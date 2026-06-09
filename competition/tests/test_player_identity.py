"""Tests for canonical Player identity: resolution + id-based Section 4 scoring.

Covers the three problems this design solves:
  * spelling/format tolerance,
  * same-surname ambiguity ("Smith"),
  * one person scoring for club OR country (international weeks).
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
    Participant,
    Player,
    ScorerPick,
    Season,
)
from competition.players import resolve_for_pick, resolve_or_create


class ResolutionTests(TestCase):
    def setUp(self):
        Player.objects.create(full_name="Erling Haaland", club="Man City")
        Player.objects.create(full_name="Jordan Smith", club="Newcastle")
        Player.objects.create(full_name="Tommy Smith", club="Everton")

    def test_exact_name_resolves(self):
        player, review = resolve_for_pick("Erling Haaland")
        self.assertEqual(player.full_name, "Erling Haaland")
        self.assertFalse(review)

    def test_surname_resolves_when_unique(self):
        player, review = resolve_for_pick("Haaland")
        self.assertEqual(player.full_name, "Erling Haaland")
        self.assertFalse(review)

    def test_club_label_disambiguates_two_smiths(self):
        player, review = resolve_for_pick("Smith (Everton)")
        self.assertEqual(player.full_name, "Tommy Smith")
        self.assertFalse(review)

    def test_bare_ambiguous_surname_flags_review(self):
        player, review = resolve_for_pick("Smith")
        self.assertIsNone(player)
        self.assertTrue(review)

    def test_unknown_name_left_unresolved(self):
        player, review = resolve_for_pick("Zlatan Ibrahimovic")
        self.assertIsNone(player)
        self.assertFalse(review)

    def test_resolve_or_create_matches_existing_by_name_and_club(self):
        existing = Player.objects.get(full_name="Erling Haaland")
        got = resolve_or_create("Haaland", club="Man City")
        self.assertEqual(got.id, existing.id)

    def test_resolve_or_create_keys_on_external_id(self):
        first = resolve_or_create("E. Haaland", external_player_id="9001")
        second = resolve_or_create("totally different text", external_player_id="9001")
        self.assertEqual(first.id, second.id)

    def test_resolve_or_create_matches_existing_from_label(self):
        # Picking "Danny Welbeck (Brighton)" from a dropdown must match the
        # existing player, not create a duplicate named with the whole label.
        existing = Player.objects.create(full_name="Danny Welbeck", club="Brighton")
        before = Player.objects.count()
        got = resolve_or_create("Danny Welbeck (Brighton)")
        self.assertEqual(got.id, existing.id)
        self.assertEqual(Player.objects.count(), before)  # no new row

    def test_resolve_or_create_strips_label_when_creating(self):
        player = resolve_or_create("Bukayo Saka (Arsenal)")
        self.assertEqual(player.full_name, "Bukayo Saka")  # not the full label
        self.assertEqual(player.club, "Arsenal")

    def test_resolve_or_create_handles_dash_label(self):
        player = resolve_or_create("Cole Palmer - Chelsea")
        self.assertEqual(player.full_name, "Cole Palmer")
        self.assertEqual(player.club, "Chelsea")


class IdScoringTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season,
            week_number=1,
            deadline=timezone.now() + timedelta(days=1),
            status=GameWeek.Status.OPEN,
        )
        self.fixture = Fixture.objects.create(
            game_week=self.gw, order=1, home_team="A", away_team="B"
        )
        self.fixture.actual_home_score = 1
        self.fixture.actual_away_score = 0
        self.fixture.save()
        user = User.objects.create_user(username="alice", password="x")
        self.participant = Participant.objects.create(
            user=user, season=self.season, display_name="Alice", join_week=1
        )

    def _pick(self, player, position=1):
        entry = Entry.objects.create(
            participant=self.participant, game_week=self.gw, submitted_at=timezone.now()
        )
        ScorerPick.objects.create(entry=entry, position=position, player=player,
                                  player_name=player.full_name)
        return entry

    def test_pick_scores_by_id_even_if_goal_text_differs(self):
        # The goal is recorded with messy text but the same Player id as the pick.
        player = Player.objects.create(full_name="Erling Haaland", club="Man City")
        FixtureGoal.objects.create(
            fixture=self.fixture, player=player, player_name="E. HAALAND", goals=2
        )
        self._pick(player, position=1)
        services.recompute_game_week(self.gw)
        ws = self.participant.weekly_scores.get(game_week=self.gw)
        # Position 1 (4) + 1 extra goal = 5, despite the text mismatch.
        self.assertEqual(ws.s4, 5)

    def test_same_person_scores_for_country_in_international_week(self):
        self.gw.is_international = True
        self.gw.save()
        # Fixture is a country match; Kane's club label is Spurs but he scores
        # for England — same Player, so the pick still matches.
        self.fixture.home_team = "England"
        self.fixture.away_team = "France"
        self.fixture.save()
        kane = Player.objects.create(
            full_name="Harry Kane", club="Spurs", national_team="England"
        )
        FixtureGoal.objects.create(
            fixture=self.fixture, player=kane, player_name="Kane", goals=1
        )
        self._pick(kane, position=2)
        services.recompute_game_week(self.gw)
        ws = self.participant.weekly_scores.get(game_week=self.gw)
        self.assertEqual(ws.s4, 3)  # position 2 = 3 pts

    def test_unresolved_pick_falls_back_to_name_match(self):
        # No Player link on the pick; tolerant name match still scores it.
        player = Player.objects.create(full_name="Cole Palmer", club="Chelsea")
        FixtureGoal.objects.create(
            fixture=self.fixture, player=player, player_name="Cole Palmer", goals=1
        )
        entry = Entry.objects.create(
            participant=self.participant, game_week=self.gw, submitted_at=timezone.now()
        )
        ScorerPick.objects.create(entry=entry, position=1, player=None,
                                  player_name="Palmer")
        services.recompute_game_week(self.gw)
        ws = self.participant.weekly_scores.get(game_week=self.gw)
        self.assertEqual(ws.s4, 4)
