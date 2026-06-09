"""Normalised schema for the tipping competition.

Predictions and results are stored separately so scoring is a deterministic,
re-runnable function of (results, entry). Computed scores are cached in
WeeklyScore / SeasonScore and recomputed on results change.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Team(models.Model):
    """An optional lookup of known team names for admin autocomplete.

    Fixtures still store team names as free text (so cup / lower-league /
    international fixtures always work). This table only drives suggestions and
    is self-populating: saving a fixture upserts its team names here (see
    competition.signals). `external_team_id` is a nullable hook for a future
    feed link (Phase II) and is unused by Phase 1 scoring.
    """

    name = models.CharField(max_length=120, unique=True)
    short_name = models.CharField(max_length=40, blank=True)
    external_team_id = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Player(models.Model):
    """A canonical footballer identity used by Section 4 scoring.

    The *person* is the unit of identity. `club` (and optional `national_team`)
    are disambiguation labels — they tell two same-surname players apart, exactly
    as "player + club" does on the paper sheet. Because identity is the person,
    a pick of "Kane" matches whether he scores for his club or his country, so
    international weeks need no separate table (just GameWeek.is_international).

    Self-populating: actual goalscorers entered on the results screen (or
    auto-filled from the feed, with `external_player_id`) upsert here, so the
    typeahead list grows on its own (see competition.players).
    """

    full_name = models.CharField(max_length=160)
    club = models.CharField(max_length=120, blank=True)  # usual domestic club
    national_team = models.CharField(max_length=120, blank=True)  # for intl weeks
    external_player_id = models.CharField(max_length=64, blank=True)  # feed id
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]
        indexes = [models.Index(fields=["full_name"])]

    def __str__(self):
        return self.label()

    def label(self, international=False):
        team = self.national_team if (international and self.national_team) else self.club
        return f"{self.full_name} ({team})" if team else self.full_name


class Season(models.Model):
    """A 40-game-week competition. Multiple seasons supported (archive + restart)."""

    name = models.CharField(max_length=120)
    start_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Only one active season at a time keeps "the open week" unambiguous.
        super().save(*args, **kwargs)
        if self.is_active:
            Season.objects.exclude(pk=self.pk).filter(is_active=True).update(
                is_active=False
            )


class Participant(models.Model):
    """A player profile, 1:1 with the auth User, scoped to one season."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="participant"
    )
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="participants"
    )
    display_name = models.CharField(max_length=120)
    # The week from which this player counts toward the table. Non-entry defaults
    # only apply from the join week onward.
    join_week = models.PositiveSmallIntegerField(default=1)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("user", "season")]
        ordering = ["display_name"]

    def __str__(self):
        return f"{self.display_name} ({self.season.name})"


class GameWeek(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        OPEN = "open", "Open"
        LOCKED = "locked", "Locked"
        RESULTS_IN = "results_in", "Results in"
        FINALISED = "finalised", "Finalised"

    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="game_weeks"
    )
    week_number = models.PositiveSmallIntegerField()  # 1..40
    title = models.CharField(max_length=160, blank=True)
    date_range_label = models.CharField(max_length=120, blank=True)
    deadline = models.DateTimeField()  # timezone-aware; set per week
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    # International week: scorer labels show the national team rather than club,
    # and matching relaxes the club hint. Same Player records — no second table.
    is_international = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("season", "week_number")]
        ordering = ["season", "week_number"]
        indexes = [models.Index(fields=["season", "week_number"])]

    def __str__(self):
        return f"GW{self.week_number} — {self.season.name}"

    @property
    def is_past_deadline(self):
        return timezone.now() >= self.deadline

    @property
    def accepts_entries(self):
        """Players may submit/edit only while open and before the deadline."""
        return self.status == self.Status.OPEN and not self.is_past_deadline

    @property
    def results_complete(self):
        """True when every fixture has a final score and every T/F has an answer."""
        fixtures = list(self.fixtures.all())
        if not fixtures:
            return False
        if any(
            f.actual_home_score is None or f.actual_away_score is None for f in fixtures
        ):
            return False
        questions = list(self.questions.all())
        if any(q.correct_answer is None for q in questions):
            return False
        return True


class Fixture(models.Model):
    """One of the 10 matches in a game week. Fully free-text / editable."""

    game_week = models.ForeignKey(
        GameWeek, on_delete=models.CASCADE, related_name="fixtures"
    )
    order = models.PositiveSmallIntegerField()  # 1..10
    home_team = models.CharField(max_length=120)
    away_team = models.CharField(max_length=120)
    kickoff = models.DateTimeField(null=True, blank=True)
    external_match_id = models.CharField(max_length=64, blank=True)  # optional feed link
    actual_home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    actual_away_score = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("game_week", "order")]
        ordering = ["game_week", "order"]

    def __str__(self):
        return f"{self.home_team} v {self.away_team}"

    @property
    def has_result(self):
        return self.actual_home_score is not None and self.actual_away_score is not None


class TrueFalseQuestion(models.Model):
    game_week = models.ForeignKey(
        GameWeek, on_delete=models.CASCADE, related_name="questions"
    )
    order = models.PositiveSmallIntegerField()  # 1..8
    text = models.CharField(max_length=300)
    correct_answer = models.BooleanField(null=True, blank=True)  # set at results time

    class Meta:
        unique_together = [("game_week", "order")]
        ordering = ["game_week", "order"]

    def __str__(self):
        return f"Q{self.order}: {self.text}"


class QuestionTemplate(models.Model):
    """A reusable True/False question (a 'question bank').

    Self-populating like Team: saving a TrueFalseQuestion upserts its text here
    (see competition.signals), so the admin gets autocomplete of previously-used
    questions when writing a week's 8. Free text is always still allowed.
    """

    text = models.CharField(max_length=300, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["text"]

    def __str__(self):
        return self.text


class FixtureGoal(models.Model):
    """A goalscorer record for a fixture, used by Section 4 scoring."""

    fixture = models.ForeignKey(Fixture, on_delete=models.CASCADE, related_name="goals")
    # Canonical identity (preferred for scoring); player_name kept as the raw
    # entered/fed text and a fallback when player is unresolved.
    player = models.ForeignKey(
        "Player", on_delete=models.SET_NULL, null=True, blank=True, related_name="goals"
    )
    player_name = models.CharField(max_length=160)
    goals = models.PositiveSmallIntegerField(default=1)
    is_penalty = models.BooleanField(default=False)
    minute = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["fixture", "player_name"]

    def __str__(self):
        return f"{self.player_name} ({self.goals}) — {self.fixture}"


class Entry(models.Model):
    """One player's predictions for one game week."""

    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="entries"
    )
    game_week = models.ForeignKey(
        GameWeek, on_delete=models.CASCADE, related_name="entries"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    is_locked = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("participant", "game_week")]
        indexes = [models.Index(fields=["participant", "game_week"])]

    def __str__(self):
        return f"Entry: {self.participant.display_name} — {self.game_week}"


class MatchPrediction(models.Model):
    entry = models.ForeignKey(
        Entry, on_delete=models.CASCADE, related_name="match_predictions"
    )
    fixture = models.ForeignKey(Fixture, on_delete=models.CASCADE)
    pred_home = models.PositiveSmallIntegerField(null=True, blank=True)
    pred_away = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        unique_together = [("entry", "fixture")]


class TotalGoalsPrediction(models.Model):
    entry = models.OneToOneField(
        Entry, on_delete=models.CASCADE, related_name="total_goals_prediction"
    )
    predicted_total = models.PositiveSmallIntegerField(null=True, blank=True)


class TrueFalseAnswer(models.Model):
    entry = models.ForeignKey(Entry, on_delete=models.CASCADE, related_name="tf_answers")
    question = models.ForeignKey(TrueFalseQuestion, on_delete=models.CASCADE)
    answer = models.BooleanField(null=True, blank=True)

    class Meta:
        unique_together = [("entry", "question")]


class ScorerPick(models.Model):
    entry = models.ForeignKey(
        Entry, on_delete=models.CASCADE, related_name="scorer_picks"
    )
    position = models.PositiveSmallIntegerField()  # 1..4 (1 = top pick)
    # Resolved identity (set when the typed text maps to exactly one Player);
    # player_name holds the raw text and drives the fallback name match.
    player = models.ForeignKey(
        "Player", on_delete=models.SET_NULL, null=True, blank=True, related_name="picks"
    )
    player_name = models.CharField(max_length=160, blank=True)
    # True when the raw text matched more than one Player and needs admin
    # reconciliation before scoring can trust it.
    needs_review = models.BooleanField(default=False)

    class Meta:
        unique_together = [("entry", "position")]
        ordering = ["entry", "position"]


class WeeklyScore(models.Model):
    """Cached per-player, per-week score. Recomputed on results change."""

    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="weekly_scores"
    )
    game_week = models.ForeignKey(
        GameWeek, on_delete=models.CASCADE, related_name="weekly_scores"
    )
    s1 = models.IntegerField(default=0)
    s2 = models.IntegerField(default=0)
    s3 = models.IntegerField(default=0)
    s4 = models.IntegerField(default=0)
    total = models.IntegerField(default=0)
    is_non_entry_default = models.BooleanField(default=False)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("participant", "game_week")]
        indexes = [models.Index(fields=["game_week", "total"])]

    def __str__(self):
        return (
            f"{self.participant.display_name} "
            f"GW{self.game_week.week_number}: {self.total}"
        )


class SeasonScore(models.Model):
    """Cached cumulative season score per player. Recomputed on results change."""

    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="season_scores"
    )
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="season_scores"
    )
    total = models.IntegerField(default=0)
    s1_total = models.IntegerField(default=0)  # cumulative Section 1, for tie-breaks
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("participant", "season")]
        indexes = [models.Index(fields=["season", "total"])]

    def __str__(self):
        return f"{self.participant.display_name} {self.season.name}: {self.total}"


class ReminderLog(models.Model):
    """Idempotency guard so a reminder window is emailed at most once per player."""

    game_week = models.ForeignKey(
        GameWeek, on_delete=models.CASCADE, related_name="reminder_logs"
    )
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)
    window_hours = models.PositiveSmallIntegerField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("game_week", "participant", "window_hours")]
