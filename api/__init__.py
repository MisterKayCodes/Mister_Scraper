from fastapi import FastAPI
from .routers.scraper import router as scraper_router

def create_app() -> FastAPI:
    app = FastAPI(
        title="Mister Scraper API",
        description="Headless Autopilot Content Harvester for X and Telegram",
        version="1.0.0"
    )
    app.include_router(scraper_router)
    return app
