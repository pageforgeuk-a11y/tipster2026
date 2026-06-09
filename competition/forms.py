"""Player-facing prediction form, built dynamically for a given game week.

Partial saves are allowed before the deadline; blank fields are permitted and
score 0 (spec §6 validation note). Score inputs are constrained to non-negative
integers server-side.
"""

from django import forms
from django.utils import timezone

from .models import GameWeek

# datetime-local input/parse format (no seconds).
DT_LOCAL = "%Y-%m-%dT%H:%M"


class GameWeekForm(forms.ModelForm):
    """Header fields for a game week, used in the Manage setup screen.

    The deadline is entered/shown in UK local time via a native datetime-local
    input; Django stores it timezone-aware.
    """

    class Meta:
        model = GameWeek
        fields = ["week_number", "title", "date_range_label", "deadline", "is_international"]
        widgets = {
            "week_number": forms.NumberInput(attrs={"min": 1, "max": 40, "class": "minput"}),
            "title": forms.TextInput(attrs={"class": "minput", "placeholder": "e.g. Opening Weekend"}),
            "date_range_label": forms.TextInput(attrs={"class": "minput", "placeholder": "e.g. Sat–Sun 9–10 Aug"}),
            "deadline": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "minput"}, format=DT_LOCAL
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deadline"].input_formats = [DT_LOCAL]
        self.fields["title"].required = False
        self.fields["date_range_label"].required = False
        # Render an existing deadline in local time for the datetime-local input.
        if self.instance and self.instance.pk and self.instance.deadline:
            self.initial["deadline"] = timezone.localtime(
                self.instance.deadline
            ).strftime(DT_LOCAL)

    def clean_week_number(self):
        n = self.cleaned_data["week_number"]
        if not (1 <= n <= 40):
            raise forms.ValidationError("Week number must be between 1 and 40.")
        return n


class EntryForm(forms.Form):
    """One form covering all four sections for a single game week.

    Field naming convention (stable, used by the template and the save logic):
      fixture_<id>_home / fixture_<id>_away  -> Section 1 predictions
      total_goals                            -> Section 2
      tf_<question_id>                        -> Section 3 (radio: "true"/"false", default true)
      scorer_<position>                       -> Section 4 (positions 1..4)
    """

    def __init__(self, *args, fixtures=None, questions=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixtures = fixtures or []
        self.questions = questions or []

        for fixture in self.fixtures:
            self.fields[f"fixture_{fixture.id}_home"] = forms.IntegerField(
                required=False, min_value=0, max_value=99,
                widget=forms.NumberInput(attrs={"class": "score-input", "inputmode": "numeric"}),
            )
            self.fields[f"fixture_{fixture.id}_away"] = forms.IntegerField(
                required=False, min_value=0, max_value=99,
                widget=forms.NumberInput(attrs={"class": "score-input", "inputmode": "numeric"}),
            )

        self.fields["total_goals"] = forms.IntegerField(
            required=False, min_value=0, max_value=999,
            widget=forms.NumberInput(attrs={"class": "score-input", "inputmode": "numeric"}),
        )

        for question in self.questions:
            # Only True/False — no blank option. Defaults to True unless the
            # player's saved answer overrides it via the form's initial data.
            self.fields[f"tf_{question.id}"] = forms.ChoiceField(
                required=False,
                choices=[("true", "True"), ("false", "False")],
                widget=forms.RadioSelect,
                initial="true",
            )

        for position in range(1, 5):
            self.fields[f"scorer_{position}"] = forms.CharField(
                required=False, max_length=160,
                widget=forms.TextInput(
                    attrs={
                        "class": "scorer-input",
                        "list": "player-suggestions",
                        "autocomplete": "off",
                        "placeholder": "Start typing a name…",
                    }
                ),
            )

    # --- typed accessors over cleaned_data ---

    def fixture_rows(self):
        """Yield (fixture, home_field, away_field) for template rendering."""
        for fixture in self.fixtures:
            yield (
                fixture,
                self[f"fixture_{fixture.id}_home"],
                self[f"fixture_{fixture.id}_away"],
            )

    def question_rows(self):
        for question in self.questions:
            yield (question, self[f"tf_{question.id}"])

    def scorer_rows(self):
        for position in range(1, 5):
            yield (position, self[f"scorer_{position}"])

    def tf_value(self, question_id):
        raw = self.cleaned_data.get(f"tf_{question_id}", "")
        if raw == "true":
            return True
        if raw == "false":
            return False
        return None
