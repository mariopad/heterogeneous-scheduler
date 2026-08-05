"""
shared/timeutils.py

One definition of "now" for the whole system.

Every metric the thesis reports -- queue wait, turnaround, makespan -- is a
difference between two timestamps written by two different processes, so the
representation has to be unambiguous. Everything here is timezone-aware UTC,
serialised as ISO-8601 with an explicit offset.

This replaces `datetime.utcnow()`, which returns a *naive* datetime that only
looks like UTC. Subtracting a naive from an aware datetime raises, comparing
them silently misleads, and it has been deprecated since Python 3.12.
"""

from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def to_iso(value: Optional[datetime]) -> Optional[str]:
    """
    Serialise a datetime for storage.

    Naive values are assumed to be UTC: agents may run older code or a
    different pydantic version, and a missing offset must not become a
    silent local-time reading.
    """
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat()


def from_iso(value) -> Optional[datetime]:
    """Parse a stored timestamp back into an aware UTC datetime."""
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def seconds_between(start, end) -> Optional[float]:
    """Elapsed seconds between two stored timestamps, or None if either is missing."""
    start = from_iso(start)
    end = from_iso(end)

    if start is None or end is None:
        return None

    return (end - start).total_seconds()
