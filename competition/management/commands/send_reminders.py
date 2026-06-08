"""Send deadline reminders. Usable from cron, CI, or by hand for testing.

The Vercel Cron path uses the HTTP endpoint (competition.cron); this command is
the same logic for local/manual runs.
"""

from django.core.management.base import BaseCommand

from competition.reminders import run_reminders


class Command(BaseCommand):
    help = "Email reminders to players who haven't submitted for the open week(s)."

    def handle(self, *args, **options):
        summary = run_reminders()
        self.stdout.write(
            self.style.SUCCESS(
                f"Reminders sent: {summary['sent']}, skipped: {summary['skipped']}"
            )
        )
