from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from app.config import Settings
from app.dependencies import ServiceContainer, build_services
from app.errors import AppError
from app.middleware import (
    RedactedAccessLogMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.routers import admin, door, registration
from app.views import TEMPLATES, WEB_ROOT


def _error_payload(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def create_app(
    settings: Settings | None = None,
    services: ServiceContainer | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        service_container = services or build_services(resolved_settings)
        application.state.settings = resolved_settings
        application.state.services = service_container
        try:
            yield
        finally:
            service_container.close()

    application = FastAPI(
        title="Door",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.router.redirect_slashes = False

    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(resolved_settings.allowed_hosts),
    )
    application.add_middleware(RequestSizeLimitMiddleware, max_bytes=64 * 1024)
    application.add_middleware(RedactedAccessLogMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)

    application.mount(
        "/static",
        StaticFiles(directory=WEB_ROOT / "static", check_dir=True),
        name="static",
    )
    application.include_router(door.router)
    application.include_router(admin.router)
    application.include_router(registration.router)

    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        if exc.html:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="error.html",
                context={"title": exc.message, "message": exc.message},
                status_code=exc.status_code,
            )
        return JSONResponse(
            _error_payload(exc.code, exc.message),
            status_code=exc.status_code,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        del exc
        if request.url.path.startswith("/admin"):
            return TEMPLATES.TemplateResponse(
                request=request,
                name="error.html",
                context={"title": "Invalid request", "message": "Invalid form submission"},
                status_code=422,
            )
        return JSONResponse(
            _error_payload("invalid_request", "Request data is invalid"),
            status_code=422,
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        message = "Not found" if exc.status_code == 404 else str(exc.detail)
        accept = request.headers.get("accept", "")
        if request.method == "GET" and "text/html" in accept:
            return TEMPLATES.TemplateResponse(
                request=request,
                name="error.html",
                context={"title": message, "message": message},
                status_code=exc.status_code,
                headers=exc.headers,
            )
        code = "not_found" if exc.status_code == 404 else "http_error"
        return JSONResponse(
            _error_payload(code, message),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    return application


app = create_app()
