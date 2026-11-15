import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, health
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("quantalens")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="QuantaLens AI Engine",
        version="0.1.0",
        # Interactive docs are useful in development; hidden in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Requested-With"],
    )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the type only. Messages can contain row data or connection details.
        logger.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return JSONResponse({"detail": "Internal server error."}, status_code=500)

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api")
    return app


app = create_app()
