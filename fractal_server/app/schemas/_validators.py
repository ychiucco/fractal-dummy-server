import os
from datetime import datetime
from datetime import timezone


def valstr(attribute: str, accept_none: bool = False):
    """
    Check that a string attribute is not an empty string, and remove the
    leading and trailing whitespace characters.

    If `accept_none`, the validator also accepts `None`.
    """

    def val(string: str):
        if string is None:
            if accept_none:
                return string
            else:
                raise ValueError(
                    f"String attribute '{attribute}' cannot be None"
                )
        s = string.strip()
        if not s:
            raise ValueError(f"String attribute '{attribute}' cannot be empty")
        return s

    return val

def valutc(attribute: str):
    def val(timestamp: datetime):
        """
        Replacing `tzinfo` with `timezone.utc` is just required by SQLite data.
        If using Postgres, this function leaves the datetime exactly as it is.
        """
        if timestamp is not None:
            return timestamp.replace(tzinfo=timezone.utc)
        return None

    return val
