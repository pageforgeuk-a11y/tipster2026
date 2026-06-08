"""Keep the Team lookup populated from whatever the admin types on fixtures.

This is a convenience only — fixtures remain free text. Each saved fixture
upserts its home/away team names into Team (case-insensitive dedupe) so the
admin's autocomplete list grows organically without manual upkeep.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Fixture, Team


def _ensure_team(name: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    if not Team.objects.filter(name__iexact=name).exists():
        Team.objects.create(name=name)


@receiver(post_save, sender=Fixture)
def populate_teams_from_fixture(sender, instance, **kwargs):
    _ensure_team(instance.home_team)
    _ensure_team(instance.away_team)
