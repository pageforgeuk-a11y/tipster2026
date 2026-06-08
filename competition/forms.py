"""Player-facing prediction form, built dynamically for a given game week.

Partial saves are allowed before the deadline; blank fields are permitted and
score 0 (spec §6 validation note). Score inputs are constrained to non-negative
integers server-side.
"""

from django import forms


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
