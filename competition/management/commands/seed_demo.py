"""Seed a demo season with one open game week and a few players.

For local exploration only:  python manage.py seed_demo
Creates an admin (admin/admin) and demo players so you can click through the
whole loop immediately.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from competition.models import (
    Fixture,
    GameWeek,
    Participant,
    Player,
    Season,
    TrueFalseQuestion,
)

TEAMS = [
    ("Arsenal", "Chelsea"),
    ("Liverpool", "Man City"),
    ("Spurs", "Man Utd"),
    ("Newcastle", "Brighton"),
    ("Aston Villa", "West Ham"),
    ("Everton", "Wolves"),
    ("Fulham", "Brentford"),
    ("Crystal Palace", "Bournemouth"),
    ("Nottm Forest", "Leicester"),
    ("Ipswich", "Southampton"),
]

QUESTIONS = [
    "At least one penalty is scored",
    "A substitute scores",
    "Two or more matches are draws",
    "A red card is shown",
    "More goals are scored by home teams than away teams",
    "At least one match finishes 0-0",
    "A hat-trick is scored",
    "The total goals is an even number",
]


class Command(BaseCommand):
    help = "Create a demo season, an open game week, and demo accounts."

    def handle(self, *args, **options):
        season, _ = Season.objects.get_or_create(
            name="Demo Season 2025/26",
            defaults={"start_date": timezone.now().date(), "is_active": True},
        )
        season.is_active = True
        season.save()

        admin, created = User.objects.get_or_create(
            username="admin", defaults={"email": "admin@example.com", "is_staff": True, "is_superuser": True}
        )
        if created:
            admin.set_password("admin")
            admin.save()
            self.stdout.write(self.style.SUCCESS("Created superuser admin/admin"))

        gw, _ = GameWeek.objects.get_or_create(
            season=season,
            week_number=1,
            defaults={
                "title": "Opening Weekend",
                "date_range_label": "Sat–Sun",
                "deadline": timezone.now() + timedelta(days=2),
                "status": GameWeek.Status.OPEN,
            },
        )
        for i, (home, away) in enumerate(TEAMS, start=1):
            Fixture.objects.get_or_create(
                game_week=gw, order=i, defaults={"home_team": home, "away_team": away}
            )
        for i, text in enumerate(QUESTIONS, start=1):
            TrueFalseQuestion.objects.get_or_create(
                game_week=gw, order=i, defaults={"text": text}
            )

        # A few well-known scorers so the pick typeahead has content, including
        # two "Smith"s at different clubs to demonstrate disambiguation.
        demo_players = [
            ("Erling Haaland", "Man City"),
            ("Mohamed Salah", "Liverpool"),
            ("Bukayo Saka", "Arsenal"),
            ("Cole Palmer", "Chelsea"),
            ("Ollie Watkins", "Aston Villa"),
            ("Jordan Smith", "Newcastle"),
            ("Tommy Smith", "Everton"),
        ]
        for full_name, club in demo_players:
            Player.objects.get_or_create(full_name=full_name, defaults={"club": club})

        # (first_name, last_name, team_name). Email = username.
        demo_users = [
            ("Alice", "Adams", "Red Lion Rovers"),
            ("Bob", "Brennan", "The Tap Room Tigers"),
            ("Carol", "Clarke", "Offside Trap"),
        ]
        for first, last, team in demo_users:
            email = f"{first.lower()}@example.com"
            user, created = User.objects.get_or_create(
                username=email,
                defaults={"email": email, "first_name": first, "last_name": last},
            )
            if created:
                user.set_password("password123")
                user.save()
            Participant.objects.get_or_create(
                user=user,
                season=season,
                defaults={"display_name": team, "join_week": 1},
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded demo season. Log in as admin/admin (staff, at /admin) "
                "or alice@example.com / password123 (player)."
            )
        )
