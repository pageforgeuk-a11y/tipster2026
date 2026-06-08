from django.apps import AppConfig


class CompetitionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'competition'

    def ready(self):
        # Register the signal that keeps the Team lookup populated.
        from . import signals  # noqa: F401
