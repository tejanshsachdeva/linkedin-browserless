from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(profile.router)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")
