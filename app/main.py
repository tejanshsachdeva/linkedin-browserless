from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.logging_config import configure_logging
from app.dependencies import shutdown_clients
from app.middleware.error_handler import register_error_handlers
from app.routers import health, profile


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield
    await shutdown_clients()


app = FastAPI(
    title="LinkedIn Profile API",
    description=(
        "Browser-free LinkedIn profile scraper. Returns Tier A (top-card) "
        "fields from server-rendered HTML plus Tier B detail sections "
        "(experience, education, skills, about, certifications, languages) via Voyager REST."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(profile.router)
