"""FastAPI application: REST API, live events and the single page web UI."""

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.gzip import GZipMiddleware

from boomarr.const import VERSION
from boomarr.web.oidc import OIDCClient
from boomarr.web.routes import api, auth, legacy
from boomarr.web.security import (
    LoginThrottle,
    ProxyHeadersMiddleware,
    SecurityHeadersMiddleware,
    SessionManager,
)

if TYPE_CHECKING:  # pragma: no cover
    from boomarr.daemon import Daemon

_LOGGER = logging.getLogger(__name__)

DIST_DIR = Path(__file__).parent / "dist"

_MISSING_UI = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Boomarr</title></head><body style="font-family:system-ui;padding:2rem">
<h1>Boomarr {version}</h1><p>The web UI has not been built. Run
<code>npm ci &amp;&amp; npm run build</code> in <code>frontend/</code>, or use the
Docker image. The API is available under <code>api/v1</code>.</p></body></html>"""


def _index_html(url_base: str) -> str | None:
    index = DIST_DIR / "index.html"
    if not index.is_file():
        return None
    html = index.read_text(encoding="utf-8")
    # The build uses relative asset URLs; <base> makes them work under any
    # url_base and for deep links such as /settings/libraries.
    return re.sub(
        r'<base href="[^"]*"\s*/?>', f'<base href="{url_base}/" />', html, count=1
    )


def create_app(daemon: Daemon) -> FastAPI:
    """Build the ASGI application for *daemon*."""
    url_base = daemon.config.server.url_base
    app = FastAPI(
        title="Boomarr",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=f"{url_base}/api/openapi.json",
    )
    app.state.daemon = daemon
    app.state.sessions = SessionManager(
        daemon.auth.session_secret,
        lambda: daemon.config.auth.session_days,
        url_base or "/",
    )
    app.state.throttle = LoginThrottle()
    app.state.oidc = OIDCClient()

    app.include_router(legacy.router, prefix=url_base)
    app.include_router(auth.router, prefix=f"{url_base}/api/v1/auth")
    app.include_router(api.router, prefix=f"{url_base}/api/v1")

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            {"detail": "Invalid request", "errors": errors}, status_code=422
        )

    index = _index_html(url_base)
    assets = DIST_DIR / "assets"

    @app.get(f"{url_base}/assets/{{name:path}}", include_in_schema=False)
    async def _asset(name: str) -> FileResponse:
        path = (assets / name).resolve()
        if not path.is_relative_to(assets.resolve()) or not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(
            path, headers={"Cache-Control": "public, max-age=31536000, immutable"}
        )

    static_files = {p.name for p in DIST_DIR.glob("*") if p.is_file()}

    @app.get(f"{url_base}/{{path:path}}", include_in_schema=False, response_model=None)
    async def _spa(path: str) -> HTMLResponse | FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        if path in static_files and path != "index.html":
            return FileResponse(DIST_DIR / path)
        if index is None:
            return HTMLResponse(_MISSING_UI.format(version=VERSION))
        return HTMLResponse(index, headers={"Cache-Control": "no-cache"})

    if url_base:

        @app.get("/", include_in_schema=False)
        async def _root() -> RedirectResponse:
            return RedirectResponse(f"{url_base}/")

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        ProxyHeadersMiddleware, trusted=daemon.config.server.trusted_proxies
    )
    return app
