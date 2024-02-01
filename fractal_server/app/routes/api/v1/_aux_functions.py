from fastapi import HTTPException
from fastapi import status
from sqlmodel import select

from ....db import AsyncSession
from ....models import LinkUserProject
from ....models import Project

async def _get_project_check_owner(
    *,
    project_id: int,
    user_id: int,
    db: AsyncSession,
) -> Project:
    """
    Check that user is a member of project and return the project.

    Args:
        project_id:
        user_id:
        db:

    Returns:
        The project object

    Raises:
        HTTPException(status_code=403_FORBIDDEN):
            If the user is not a member of the project
        HTTPException(status_code=404_NOT_FOUND):
            If the project does not exist
    """
    project = await db.get(Project, project_id)
    link_user_project = await db.get(LinkUserProject, (project_id, user_id))
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if not link_user_project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Not allowed on project {project_id}",
        )
    return project

async def _check_project_exists(
    *,
    project_name: str,
    user_id: int,
    db: AsyncSession,
) -> None:
    """
    Check that no other project with this name exists for this user.

    Args:
        project_name: Project name
        user_id: User ID
        db:

    Raises:
        HTTPException(status_code=422_UNPROCESSABLE_ENTITY):
            If such a project already exists
    """
    stm = (
        select(Project)
        .join(LinkUserProject)
        .where(Project.name == project_name)
        .where(LinkUserProject.user_id == user_id)
    )
    res = await db.execute(stm)
    if res.scalars().all():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Project name ({project_name}) already in use",
        )
