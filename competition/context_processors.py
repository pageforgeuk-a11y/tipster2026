"""Template context shared across the site."""

from .models import Season


def active_season(request):
    user = getattr(request, "user", None)
    is_organiser = bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.groups.filter(name="Organiser").exists())
    )
    return {
        "active_season": Season.objects.filter(is_active=True).first(),
        "is_organiser": is_organiser,
    }
