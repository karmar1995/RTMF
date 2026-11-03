from datetime import datetime

def to_server_datetime_and_string(value: str) -> tuple[datetime, str]:
    """
    Parse ISO-8601 datetime string, convert it to the server's local timezone,
    and return:
      1. a timezone-aware datetime object
      2. a formatted string: YYYY-MM-DD HH:MM:SS

    Example input:
        2026-03-29T18:29:06.371332+00:00
    """
    dt = datetime.fromisoformat(value)   # parse ISO string
    server_dt = dt.astimezone()          # convert to server local timezone
    formatted = server_dt.strftime("%Y-%m-%d %H:%M:%S")
    return server_dt, formatted