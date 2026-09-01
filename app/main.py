from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.dependencies import shutdown_clients
from app.middleware.error_handler import register_error_handlers
from app.routers import admin_session, health, profile


def _docs_enabled() -> bool:
    settings = get_settings()
    return settings.enable_docs or settings.api_key is None


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield
    await shutdown_clients()


_show_docs = _docs_enabled()

app = FastAPI(
    title="LinkedIn Profile API",
    description=(
        "Browser-free LinkedIn profile scraper. Returns Tier A (top-card) "
        "fields from server-rendered HTML plus Tier B detail sections "
        "(experience, education, skills, about, certifications, languages) via Voyager REST."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _show_docs else None,
    redoc_url="/redoc" if _show_docs else None,
    openapi_url="/openapi.json" if _show_docs else None,
)

register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(profile.router)
app.include_router(admin_session.router)


@app.get("/", include_in_schema=False)
async def root():
    if _show_docs:
        return RedirectResponse(url="/docs")
    return JSONResponse({"status": "ok"})
