from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from pydantic import validator

from ._validators import valstr
from ._validators import valutc


__all__ = (
    "ProjectCreate",
    "ProjectRead",
    "ProjectUpdate",
)


class _ProjectBase(BaseModel):

    name: str
    read_only: bool = False


class ProjectCreate(_ProjectBase):

    _name = validator("name", allow_reuse=True)(valstr("name"))


class ProjectRead(_ProjectBase):

    id: int
    timestamp_created: datetime

    _timestamp_created = validator("timestamp_created", allow_reuse=True)(
        valutc("timestamp_created")
    )


class ProjectUpdate(_ProjectBase):

    name: Optional[str]
    read_only: Optional[bool]

    _name = validator("name", allow_reuse=True)(valstr("name"))
