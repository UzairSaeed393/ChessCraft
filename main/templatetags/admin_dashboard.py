from __future__ import annotations

from datetime import timedelta

from django import template
from django.contrib.auth import get_user_model
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from analysis.models import SavedAnalysis
from user.models import Game

register = template.Library()


def _safe_count(qs):
    try:
        return qs.count()
    except (OperationalError, ProgrammingError):
        return None


def _safe_distinct_count(qs, field_name: str):
    try:
        return qs.values(field_name).distinct().count()
    except (OperationalError, ProgrammingError):
        return None


@register.simple_tag
def admin_dashboard_stats():
    """Return basic daily/weekly/monthly metrics for the admin index.

    Notes:
    - "Visitors" is approximated via users who logged in (User.last_login).
    - "Games fetched" uses Game.fetched_at (added in user migration 0004).
    """

    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    User = get_user_model()

    stats = {
        "visitors_day": _safe_distinct_count(User.objects.filter(last_login__gte=day_ago), "pk"),
        "visitors_week": _safe_distinct_count(User.objects.filter(last_login__gte=week_ago), "pk"),
        "visitors_month": _safe_distinct_count(User.objects.filter(last_login__gte=month_ago), "pk"),

        "new_users_day": _safe_count(User.objects.filter(date_joined__gte=day_ago)),
        "new_users_week": _safe_count(User.objects.filter(date_joined__gte=week_ago)),
        "new_users_month": _safe_count(User.objects.filter(date_joined__gte=month_ago)),

        "games_fetched_day": _safe_count(Game.objects.filter(fetched_at__gte=day_ago)),
        "games_fetched_week": _safe_count(Game.objects.filter(fetched_at__gte=week_ago)),
        "games_fetched_month": _safe_count(Game.objects.filter(fetched_at__gte=month_ago)),

        "analyses_day": _safe_count(SavedAnalysis.objects.filter(game_date__gte=day_ago)),
        "analyses_week": _safe_count(SavedAnalysis.objects.filter(game_date__gte=week_ago)),
        "analyses_month": _safe_count(SavedAnalysis.objects.filter(game_date__gte=month_ago)),

        "total_users": _safe_count(User.objects.all()),
        "total_games": _safe_count(Game.objects.all()),
        "total_analyses": _safe_count(SavedAnalysis.objects.all()),
    }

    return stats
