from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from django import template

register = template.Library()


@dataclass(frozen=True)
class ParsedTimeControl:
    base_seconds: int
    increment_seconds: int
    raw: str


_TIME_CONTROL_RE = re.compile(r"^(?P<base>\d+)(?:\+(?P<inc>\d+))?$")


def _parse_time_control(value: object) -> Optional[ParsedTimeControl]:
    if value is None:
        return None

    raw = str(value).strip()
    if not raw or raw.upper() == "N/A":
        return None

    # Chess.com uses formats like:
    # - "600" (10 min)
    # - "300+2" (5+2)
    # - "1/259200" (daily/correspondence) -> we don't classify these here
    if "/" in raw:
        return None

    match = _TIME_CONTROL_RE.match(raw)
    if not match:
        return None

    base_seconds = int(match.group("base"))
    increment_seconds = int(match.group("inc") or 0)
    return ParsedTimeControl(base_seconds=base_seconds, increment_seconds=increment_seconds, raw=raw)


def _label(parsed: ParsedTimeControl) -> str:
    base = parsed.base_seconds
    inc = parsed.increment_seconds

    if inc > 0:
        # Convert 300+2 to 5+2
        if base % 60 == 0:
            return f"{base // 60}+{inc}"
        return f"{base}+{inc}"

    if base < 60:
        return f"{base} sec"

    if base % 60 == 0:
        minutes = base // 60
        return f"{minutes} min"

    # Fallback for unusual values
    return f"{base} sec"


def _category(parsed: ParsedTimeControl) -> str:
    base = parsed.base_seconds
    inc = parsed.increment_seconds

    # Handle increment by estimating total time.
    # Common heuristic (used by many chess sites): base + 40 * increment.
    estimated_seconds = base + (40 * inc)

    # Categories requested:
    # - Bullet: 30 sec to 2 min (and common increment formats like 2+1)
    # - Blitz: 3 to 5 min (and common increment formats like 5+2)
    # - Rapid: 10 to 30 min
    #
    # Using estimated time lets increments stay in the intended bucket.
    if estimated_seconds < 180:
        return "Bullet"

    if 180 <= estimated_seconds < 600:
        return "Blitz"

    if 600 <= estimated_seconds <= 1800:
        return "Rapid"

    return "Other"


@register.filter(name="time_control_label")
def time_control_label(value: object) -> str:
    parsed = _parse_time_control(value)
    return _label(parsed) if parsed else (str(value).strip() if value is not None else "")


@register.filter(name="time_control_category")
def time_control_category(value: object) -> str:
    parsed = _parse_time_control(value)
    return _category(parsed) if parsed else ""


@register.filter(name="time_control_icon")
def time_control_icon(value: object) -> str:
    """Return a Bootstrap Icons class name for the parsed time control category."""
    parsed = _parse_time_control(value)
    if not parsed:
        return ""

    cat = _category(parsed)
    if cat == "Rapid":
        return "bi-clock"
    if cat == "Blitz":
        return "bi-stopwatch"
    if cat == "Bullet":
        return "bi-lightning-charge"
    return "bi-question-circle"
