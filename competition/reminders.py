"""Deadline reminder logic (spec §9).

Idempotent: each (game_week, participant, window) is emailed at most once,
guarded by ReminderLog. Safe to run on any schedule (e.g. Vercel Cron hourly).
"""

from __future__ import annotations

from django.conf import settings
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from .emailing import send_email
from .models import Entry, GameWeek, Participant, ReminderLog


def _due_window(game_week: GameWeek, windows) -> int | None:
    """Return the reminder window (hours) that is currently 'live', if any.

    A window N is live when we are within N hours of the deadline but not yet
    within the next (smaller) window — so each window fires in its own slice.
    """
    now = timezone.now()
    if now >= game_week.deadline:
        return None
    hours_left = (game_week.deadline - now).total_seconds() / 3600.0
    # Largest window whose threshold we've crossed.
    eligible = sorted((w for w in windows if hours_left <= w), reverse=False)
    return eligible[0] if eligible else None


def run_reminders(windows=None) -> dict:
    """Send reminders for all open, pre-deadline weeks. Returns a summary dict."""
    windows = windows or settings.REMINDER_WINDOWS_HOURS
    sent = 0
    skipped = 0

    open_weeks = GameWeek.objects.filter(status=GameWeek.Status.OPEN).select_related(
        "season"
    )
    for game_week in open_weeks:
        window = _due_window(game_week, windows)
        if window is None:
            continue

        # Participants who count this week and have not submitted.
        submitted_ids = set(
            Entry.objects.filter(
                game_week=game_week, submitted_at__isnull=False
            ).values_list("participant_id", flat=True)
        )
        participants = Participant.objects.filter(
            season=game_week.season, join_week__lte=game_week.week_number
        ).select_related("user")

        for participant in participants:
            if participant.id in submitted_ids:
                continue
            if not participant.user.email:
                skipped += 1
                continue
            # Idempotency: claim the (week, participant, window) slot first.
            try:
                ReminderLog.objects.create(
                    game_week=game_week,
                    participant=participant,
                    window_hours=window,
                )
            except IntegrityError:
                skipped += 1
                continue

            if _send_one(participant, game_week, window):
                sent += 1

    return {"sent": sent, "skipped": skipped}


def _send_one(participant, game_week, window) -> bool:
    deadline_local = timezone.localtime(game_week.deadline)
    url = settings.SITE_URL.rstrip("/") + reverse(
        "entry", args=[game_week.week_number]
    )
    subject = f"Reminder: GW{game_week.week_number} predictions close soon"
    body = (
        f"Hi {participant.display_name},\n\n"
        f"You haven't submitted your predictions for Game Week "
        f"{game_week.week_number} yet.\n"
        f"The deadline is {deadline_local:%a %d %b %Y, %H:%M} (UK time) — "
        f"about {window} hours away.\n\n"
        f"Get your entry in here: {url}\n\n"
        f"Good luck!\nK.H.S.S.C. Tipsters"
    )
    return send_email(participant.user.email, subject, body)
