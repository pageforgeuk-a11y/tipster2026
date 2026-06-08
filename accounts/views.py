"""Account registration. Creates the User + a Participant joined to the active
season at the current open week (spec §6.1)."""

from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import redirect, render

from competition.models import GameWeek, Participant, Season

from .forms import RegistrationForm


def _current_week_number(season: Season) -> int:
    """Best guess at the week a new player joins: the open week, else the latest."""
    open_gw = (
        GameWeek.objects.filter(season=season, status=GameWeek.Status.OPEN)
        .order_by("week_number")
        .first()
    )
    if open_gw:
        return open_gw.week_number
    latest = GameWeek.objects.filter(season=season).order_by("-week_number").first()
    return latest.week_number if latest else 1


def register(request):
    season = Season.objects.filter(is_active=True).first()

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            if season is None:
                messages.error(
                    request,
                    "Registration is not open yet — no active season. "
                    "Please check back soon.",
                )
                return render(request, "registration/register.html", {"form": form})

            with transaction.atomic():
                user = form.save()
                Participant.objects.create(
                    user=user,
                    season=season,
                    display_name=form.cleaned_data["team_name"],
                    join_week=_current_week_number(season),
                )
            login(request, user)
            messages.success(request, "Welcome! Your account is ready.")
            return redirect("dashboard")
    else:
        form = RegistrationForm()

    return render(
        request, "registration/register.html", {"form": form, "season": season}
    )
