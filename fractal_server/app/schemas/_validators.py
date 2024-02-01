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


def val_absolute_path(attribute: str):
    """
    Check that a string attribute is an absolute path
    """

    def val(string: str):
        if string is None:
            raise ValueError(f"String attribute '{attribute}' cannot be None")
        s = string.strip()
        if not s:
            raise ValueError(f"String attribute '{attribute}' cannot be empty")
        if not os.path.isabs(s):
            raise ValueError(
                f"String attribute '{attribute}' must be an absolute path "
                f"(given '{s}')."
            )
        return s

    return val


def val_unique_list(attribute: str):
    def val(must_be_unique: list):
        if must_be_unique is not None:
            if len(set(must_be_unique)) != len(must_be_unique):
                raise ValueError(f"`{attribute}` list has repetitions")
        return must_be_unique

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
