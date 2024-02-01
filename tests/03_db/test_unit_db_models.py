import datetime

import pytest
from devtools import debug
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from fractal_server.app.models import Project
from fractal_server.config import get_settings
from fractal_server.syringe import Inject


async def test_projects(db):
    p1 = Project(name="project", read_only=True)
    p2 = Project(name="project")
    assert p1.timestamp_created is not None
    assert p2.timestamp_created is not None
    db.add(p1)
    db.add(p2)
    await db.commit()
    db.expunge_all()

    project_query = await db.execute(select(Project))
    project_list = project_query.scalars().all()

    assert len(project_list) == 2
    # test defaults
    for project in project_list:
        assert project.user_list == []
        # delete
        await db.delete(project)

    project_query = await db.execute(select(Project))
    assert project_query.scalars().one_or_none() is None


async def test_project_name_not_unique(MockCurrentUser, db, project_factory):
    """
    GIVEN the fractal_server database
    WHEN I create two projects with the same name and same user
    THEN no exception is raised
    """
    PROJ_NAME = "project name"
    async with MockCurrentUser() as user:
        p0 = await project_factory(user, name=PROJ_NAME)
        p1 = await project_factory(user, name=PROJ_NAME)

    stm = select(Project).where(Project.name == PROJ_NAME)
    res = await db.execute(stm)
    project_list = res.scalars().all()
    assert len(project_list) == 2
    assert p0.model_dump() in [p.model_dump() for p in project_list]
    assert p1.model_dump() in [p.model_dump() for p in project_list]


async def test_timestamp(db):
    """
    SQLite encodes datetime objects as strings; therefore when extracting a
    timestamp from the db, it is not timezone-aware by default.
    Postgres, on the other hand, saves timestamps together with their timezone.
    This test asserts this behaviour.
    """
    p = Project(name="project")
    assert isinstance(p.timestamp_created, datetime.datetime)
    assert p.timestamp_created.tzinfo == datetime.timezone.utc
    assert p.timestamp_created.tzname() == "UTC"

    db.add(p)
    await db.commit()
    db.expunge_all()

    query = await db.execute(select(Project))
    project = query.scalars().one()

    assert isinstance(project.timestamp_created, datetime.datetime)

    DB_ENGINE = Inject(get_settings).DB_ENGINE
    if DB_ENGINE == "sqlite":
        assert project.timestamp_created.tzinfo is None
        assert project.timestamp_created.tzname() is None
    else:  # postgres
        assert project.timestamp_created.tzinfo == datetime.timezone.utc
        assert project.timestamp_created.tzname() == "UTC"
