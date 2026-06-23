from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import CrewError

# Default timezone for new instances (KST). Containers honour the TZ env var.
DEFAULT_TIMEZONE = "Asia/Seoul"


def validate_timezone(zone: str) -> None:
    """Raise CrewError unless `zone` is a known IANA timezone (e.g. Asia/Seoul).

    Validated against the host tz database via zoneinfo; the same zone names
    resolve inside the container (it ships tzdata).
    """
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CrewError(f"invalid timezone: {zone!r}") from exc
