"""Session filter — pure function, checks if a UTC hour is within trading window."""


def is_in_session(
    utc_hour: int,
    session_start: int = 7,
    session_end: int = 21,
) -> bool:
    """Return True if *utc_hour* falls within the London + New York session.

    Default window: 07:00–21:00 UTC (inclusive start, exclusive end).

    Args:
        utc_hour: The hour in UTC (0–23).
        session_start: Session start hour (inclusive).
        session_end: Session end hour (exclusive).
    """
    return session_start <= utc_hour < session_end
