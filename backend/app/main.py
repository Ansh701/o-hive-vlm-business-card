from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles

from backend.app.api import build_api_router
from backend.app.config import Settings, get_settings
from backend.app.db import SessionFactory
from backend.app.inference import InferenceClient
from backend.app.logging import configure_logging, get_logger
from backend.app.rate_limit import SlidingWindowLimiter
from backend.app.services import Extractor, ServiceError

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

configure_logging()
logger = get_logger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    inference_client: Extractor | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    sessions = session_factory or SessionFactory
    extractor = inference_client or InferenceClient(runtime_settings)
    limiter = SlidingWindowLimiter()

    app = FastAPI(
        title="O-HIVE Card Leads",
        debug=False,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = runtime_settings
    app.state.session_factory = sessions
    app.state.inference_client = extractor
    app.state.rate_limiter = limiter

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=runtime_settings.allowed_hosts)
    if runtime_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=runtime_settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-Request-ID"],
        )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_completed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=round((perf_counter() - started) * 1000, 1),
            )
            raise
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if runtime_settings.environment == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started) * 1000, 1),
        )
        return response

    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "code": "validation_error"},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        database_connected = False
        try:
            async with sessions() as session:
                await session.execute(text("SELECT 1"))
                database_connected = True
                await session.execute(text("SELECT 1 FROM batches LIMIT 1"))
                await session.execute(text("SELECT 1 FROM leads LIMIT 1"))
        except SQLAlchemyError:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "database": "schema_missing" if database_connected else "unavailable",
                },
            )
        return JSONResponse(content={"status": "ready", "database": "ok"})

    app.include_router(
        build_api_router(
            settings=runtime_settings,
            session_factory=sessions,
            inference_client=extractor,
            limiter=limiter,
        )
    )

    frontend_root = runtime_settings.frontend_dist.resolve()
    frontend_index = frontend_root / "index.html"
    frontend_assets = frontend_root / "assets"
    if frontend_index.is_file():
        if frontend_assets.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=frontend_assets),
                name="frontend-assets",
            )

        @app.get("/{frontend_path:path}", include_in_schema=False)
        def serve_frontend(frontend_path: str) -> FileResponse:
            if frontend_path == "api" or frontend_path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate: Path = (frontend_root / frontend_path).resolve()
            if (
                frontend_path
                and candidate.is_relative_to(frontend_root)
                and candidate.is_file()
            ):
                return FileResponse(candidate)
            return FileResponse(frontend_index)

    return app


app = create_app()
