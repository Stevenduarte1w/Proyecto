from __future__ import annotations

import base64
import hmac
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from orchestrator.api.v1.router import api_router
from orchestrator.core.config import get_settings
from orchestrator.core.lifespan import lifespan
from orchestrator.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def protect_dashboard(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        protected = request.url.path.startswith(
            (
                "/dashboard",
                "/api/v1/seo",
                "/api/v1/page-executions",
                "/api/v1/post-monitor",
                "/api/v1/instagram",
            )
        )
        basic_authenticated = (
            bool(settings.dashboard_user and settings.dashboard_pass)
            and _valid_basic_auth(
                request.headers.get("Authorization", ""),
                settings.dashboard_user,
                settings.dashboard_pass,
            )
        )
        page_flow_write = _is_bot_write_path(request.method, request.url.path)
        if (
            protected
            and not page_flow_write
            and settings.dashboard_user
            and settings.dashboard_pass
            and not basic_authenticated
        ):
            headers = {"WWW-Authenticate": 'Basic realm="SEO Dashboard"'}
            if request.url.path.startswith("/api/"):
                return JSONResponse(
                    {"detail": "Not authenticated"},
                    status_code=401,
                    headers=headers,
                )
            return Response(
                "No autorizado",
                status_code=401,
                headers=headers,
            )
        return await call_next(request)

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    frontend_directory = _find_frontend_directory()
    if frontend_directory is not None:
        app.mount(
            "/dashboard",
            StaticFiles(directory=frontend_directory, html=True),
            name="dashboard",
        )

        @app.get("/", include_in_schema=False)
        async def dashboard_redirect() -> RedirectResponse:
            return RedirectResponse(url="/dashboard/")

    return app


def _find_frontend_directory() -> Path | None:
    candidates = (
        Path.cwd() / "frontend",
        Path(__file__).resolve().parents[2] / "frontend",
    )
    return next((path for path in candidates if (path / "index.html").is_file()), None)


def _valid_basic_auth(header: str, expected_user: str, expected_password: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        user, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(user, expected_user) and hmac.compare_digest(
        password,
        expected_password,
    )


def _is_bot_write_path(method: str, path: str) -> bool:
    if method != "PUT":
        return False
    prefix = "/api/v1/page-executions/"
    if not path.startswith(prefix):
        return False
    parts = path.removeprefix(prefix).split("/")
    return (
        len(parts) >= 2
        and parts[0].isdigit()
        and parts[1] in {"log", "artifacts"}
    )
