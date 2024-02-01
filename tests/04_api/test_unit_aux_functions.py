import pytest
from fastapi import HTTPException

from fractal_server.app.routes.api.v1._aux_functions import (
    _get_project_check_owner,
)


async def test_get_project_check_owner(
    MockCurrentUser,
    project_factory,
    db,
):
    async with MockCurrentUser() as other_user:
        other_project = await project_factory(other_user)

    async with MockCurrentUser() as user:
        project = await project_factory(user)

        # Test success
        await _get_project_check_owner(
            project_id=project.id, user_id=user.id, db=db
        )

        # Test fail 1
        with pytest.raises(HTTPException) as err:
            await _get_project_check_owner(
                project_id=project.id + 1, user_id=user.id, db=db
            )
        assert err.value.status_code == 404
        assert err.value.detail == "Project not found"

        # Test fail 2
        with pytest.raises(HTTPException) as err:
            await _get_project_check_owner(
                project_id=other_project.id, user_id=user.id, db=db
            )
        assert err.value.status_code == 403
        assert err.value.detail == f"Not allowed on project {other_project.id}"

