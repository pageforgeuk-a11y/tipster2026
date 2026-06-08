"""Unit tests for the pure scoring engine (spec §4 + §13).

Covers: outcome points, the exact-score bonus stacking, the 0–4 vs 5+ combined
split, the total-goals bands, the all-correct T/F bonus, and multi-goal scorer
picks. No database required.
"""

from django.test import SimpleTestCase

from competition import scoring


class Section1Tests(SimpleTestCase):
    def test_correct_home_win_outcome_only(self):
        # Predict 2-0 (home win), actual 1-0 (home win), not exact -> 3 pts.
        self.assertEqual(scoring.score_fixture(2, 0, 1, 0), 3)

    def test_correct_draw_outcome_only(self):
        # Predict 1-1 (draw), actual 2-2 (draw), not exact -> 4 pts.
        self.assertEqual(scoring.score_fixture(1, 1, 2, 2), 4)

    def test_correct_away_win_outcome_only(self):
        # Predict 0-2 (away win), actual 1-3 (away win), not exact -> 5 pts.
        self.assertEqual(scoring.score_fixture(0, 2, 1, 3), 5)

    def test_wrong_outcome_scores_zero(self):
        self.assertEqual(scoring.score_fixture(2, 0, 0, 1), 0)

    def test_exact_away_win_low_scoring_stacks(self):
        # Spec example: predict 1-2, actual 1-2 -> away 5 + bonus 5 = 10.
        self.assertEqual(scoring.score_fixture(1, 2, 1, 2), 10)

    def test_exact_draw_high_scoring_stacks(self):
        # Spec example: predict 3-3, actual 3-3 -> draw 4 + bonus 7 = 11.
        self.assertEqual(scoring.score_fixture(3, 3, 3, 3), 11)

    def test_exact_score_combined_exactly_four_uses_low_bonus(self):
        # Combined = 4 -> +5. Home win 3 + 5 = 8.
        self.assertEqual(scoring.score_fixture(3, 1, 3, 1), 8)

    def test_exact_score_combined_five_uses_high_bonus(self):
        # Combined = 5 -> +7. Home win 3 + 7 = 10.
        self.assertEqual(scoring.score_fixture(4, 1, 4, 1), 10)

    def test_missing_result_scores_zero(self):
        self.assertEqual(scoring.score_fixture(1, 0, None, None), 0)

    def test_missing_prediction_scores_zero(self):
        self.assertEqual(scoring.score_fixture(None, None, 1, 0), 0)

    def test_section1_sums_fixtures(self):
        preds = [(2, 0), (1, 1), (0, 2)]
        results = [(1, 0), (2, 2), (1, 3)]
        self.assertEqual(scoring.score_section1(preds, results), 3 + 4 + 5)


class Section2Tests(SimpleTestCase):
    def test_bands(self):
        self.assertEqual(scoring.score_section2(20, 20), 5)  # diff 0
        self.assertEqual(scoring.score_section2(20, 21), 3)  # diff 1
        self.assertEqual(scoring.score_section2(20, 22), 2)  # diff 2
        self.assertEqual(scoring.score_section2(20, 23), 1)  # diff 3
        self.assertEqual(scoring.score_section2(20, 24), 0)  # diff 4
        self.assertEqual(scoring.score_section2(20, 30), 0)

    def test_none_scores_zero(self):
        self.assertEqual(scoring.score_section2(None, 20), 0)


class Section3Tests(SimpleTestCase):
    def test_two_points_each(self):
        answers = [True, False, True, False, True, False, True, False]
        correct = [True, False, True, False, True, False, True, True]  # 7 right
        self.assertEqual(scoring.score_section3(answers, correct), 14)

    def test_all_correct_bonus(self):
        answers = [True] * 8
        correct = [True] * 8
        # 16 + 4 bonus = 20 (max).
        self.assertEqual(scoring.score_section3(answers, correct), 20)

    def test_blank_answer_breaks_all_correct(self):
        answers = [True] * 7 + [None]
        correct = [True] * 8
        self.assertEqual(scoring.score_section3(answers, correct), 14)

    def test_ungraded_question_no_bonus(self):
        answers = [True] * 8
        correct = [True] * 7 + [None]
        # 14, no bonus because not all graded.
        self.assertEqual(scoring.score_section3(answers, correct), 14)


class Section4Tests(SimpleTestCase):
    def test_position_values(self):
        picks = [(1, "A"), (2, "B"), (3, "C"), (4, "D")]
        goals = {"A": 1, "B": 1, "C": 1, "D": 1}
        self.assertEqual(scoring.score_section4(picks, goals), 4 + 3 + 2 + 1)

    def test_hat_trick_bonus(self):
        # Spec example: 4-point pick scores a hat-trick -> 4 + (3-1) = 6.
        picks = [(1, "Haaland")]
        goals = {"Haaland": 3}
        self.assertEqual(scoring.score_section4(picks, goals), 6)

    def test_no_goal_scores_zero(self):
        picks = [(1, "Nobody")]
        goals = {"Haaland": 2}
        self.assertEqual(scoring.score_section4(picks, goals), 0)

    def test_case_insensitive_match(self):
        picks = [(2, "  haaland ")]
        goals = {"Haaland": 1}
        self.assertEqual(scoring.score_section4(picks, goals), 3)

    def test_surname_fallback_match(self):
        picks = [(1, "Salah")]
        goals = {"Mohamed Salah": 2}
        self.assertEqual(scoring.score_section4(picks, goals), 5)  # 4 + 1

    def test_blank_pick_skipped(self):
        picks = [(1, ""), (2, "Haaland")]
        goals = {"Haaland": 1}
        self.assertEqual(scoring.score_section4(picks, goals), 3)


class SectionScoresTests(SimpleTestCase):
    def test_total(self):
        s = scoring.SectionScores(s1=10, s2=5, s3=20, s4=6)
        self.assertEqual(s.total, 41)
