from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config, db
from app.routes import entries, pages, settings
from app.templating import STATIC_DIR


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        url = config.database_url()
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        db.migrate(url)
        db.init_engine(url)
        yield

    app = FastAPI(
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        # Spec: no outbound network calls. FastAPI's OpenTelemetry hooks are opt-in, but make it explicit.
        telemetry={"tracing": False, "metrics": False, "logs": False, "auto_configure": False},
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages.router)
    app.include_router(entries.router)
    app.include_router(settings.router)
    return app


app = create_app()
