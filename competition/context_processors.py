"""Template context shared across the site."""

from .models import Season


def active_season(request):
    return {"active_season": Season.objects.filter(is_active=True).first()}
