from fastapi import FastAPI


def collect_routers(app: FastAPI) -> None:
    from .app.api import router_default
    from .app.api import router_v1
    from .app.security import auth_router

    app.include_router(router_default, prefix="/api")
    app.include_router(router_v1, prefix="/api/v1")
    app.include_router(auth_router, prefix="/auth", tags=["auth"])


def start_application() -> FastAPI:
    app = FastAPI()
    collect_routers(app)

    return app