"""
`api/v1` module
"""
from fastapi import APIRouter


from .project import router as project_router

router_api_v1 = APIRouter()

router_api_v1.include_router(
    project_router, prefix="/project", tags=["Projects"]
)
