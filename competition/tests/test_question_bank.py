"""The question bank self-populates from used questions and offers autocomplete,
but never constrains what the admin can type (free text always allowed)."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from competition.models import GameWeek, QuestionTemplate, Season, TrueFalseQuestion


class QuestionBankTests(TestCase):
    def setUp(self):
        self.season = Season.objects.create(name="S", is_active=True)
        self.gw = GameWeek.objects.create(
            season=self.season, week_number=1, deadline=timezone.now() + timedelta(days=1)
        )

    def test_saving_question_adds_to_bank(self):
        TrueFalseQuestion.objects.create(
            game_week=self.gw, order=1, text="A penalty is scored"
        )
        self.assertTrue(QuestionTemplate.objects.filter(text="A penalty is scored").exists())

    def test_bank_dedupes_case_insensitively(self):
        TrueFalseQuestion.objects.create(game_week=self.gw, order=1, text="A red card is shown")
        gw2 = GameWeek.objects.create(
            season=self.season, week_number=2, deadline=timezone.now() + timedelta(days=2)
        )
        TrueFalseQuestion.objects.create(game_week=gw2, order=1, text="a red card is shown")
        self.assertEqual(
            QuestionTemplate.objects.filter(text__iexact="a red card is shown").count(), 1
        )

    def test_admin_change_page_exposes_question_datalist(self):
        TrueFalseQuestion.objects.create(game_week=self.gw, order=1, text="A substitute scores")
        User.objects.create_superuser("admin", "a@e.com", "pw")
        self.client.force_login(User.objects.get(username="admin"))
        html = self.client.get(
            f"/admin/competition/gameweek/{self.gw.id}/change/", SERVER_NAME="localhost"
        ).content.decode()
        self.assertIn('id="question-suggestions"', html)
        self.assertIn('list="question-suggestions"', html)
        self.assertIn("A substitute scores", html)
