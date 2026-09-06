"""Anchor goals on the game week (fixture becomes optional).

Section 4 scoring aggregates goals to a week total regardless of match, and the
results screen now records goals per picked player at the week level. Existing
fixture-linked goals are backfilled with their fixture's game week so re-scoring
historical weeks reproduces the same figures.
"""

from django.db import migrations, models
import django.db.models.deletion


def backfill_game_week(apps, schema_editor):
    FixtureGoal = apps.get_model("competition", "FixtureGoal")
    for goal in FixtureGoal.objects.select_related("fixture").all():
        if goal.game_week_id is None and goal.fixture_id is not None:
            goal.game_week_id = goal.fixture.game_week_id
            goal.save(update_fields=["game_week"])


class Migration(migrations.Migration):

    dependencies = [
        ("competition", "0005_organiser_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="fixturegoal",
            name="game_week",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="week_goals",
                to="competition.gameweek",
            ),
        ),
        migrations.AlterField(
            model_name="fixturegoal",
            name="fixture",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="goals",
                to="competition.fixture",
            ),
        ),
        migrations.RunPython(backfill_game_week, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="fixturegoal",
            name="game_week",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="week_goals",
                to="competition.gameweek",
            ),
        ),
        migrations.AlterModelOptions(
            name="fixturegoal",
            options={"ordering": ["game_week", "player_name"]},
        ),
    ]
