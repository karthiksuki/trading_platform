from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import initialize_schema
from app.routers import admin, health, markets, payments, realtime, trading, users


def create_app() -> FastAPI:
    application = FastAPI(title=settings.app_title, version=settings.app_version)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.on_event("startup")
    def on_startup() -> None:
        initialize_schema()

    application.include_router(health.router)
    application.include_router(markets.router)
    application.include_router(trading.router)
    application.include_router(payments.router)
    application.include_router(users.router)
    application.include_router(admin.router)
    application.include_router(realtime.router)
    return application


app = create_app()
