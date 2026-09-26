"""REST API used by the web UI (and available to scripts with the API key)."""

import asyncio
import contextlib
import json
import logging
import os
import platform
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from boomarr.config import ConfigError, SQLiteDatabaseConfig
from boomarr.config_store import ConfigConflictError, ConfigReadOnlyError
from boomarr.const import VERSION
from boomarr.health import run_checks
from boomarr.languages import known_languages
from boomarr.status import collect_status
from boomarr.web import connections
from boomarr.web.security import Principal, require_user

if TYPE_CHECKING:  # pragma: no cover
    from boomarr.daemon import Daemon

_LOGGER = logging.getLogger(__name__)
_SSE_KEEPALIVE = 15.0

router = APIRouter(tags=["api"], dependencies=[Depends(require_user)])
User = Annotated[Principal, Depends(require_user)]


def _daemon(request: Request) -> Daemon:
    return request.app.state.daemon


def _config_error(exc: ConfigError) -> JSONResponse:
    return JSONResponse(
        {"detail": exc.message, "errors": exc.errors},
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@router.get("/system/status")
async def system_status(request: Request, user: User) -> dict[str, Any]:
    daemon = _daemon(request)
    config = daemon.config
    database = config.database
    return {
        "version": VERSION,
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "pid": os.getpid(),
        "started_at": daemon.started_at,
        "uptime_seconds": time.time() - daemon.started_at,
        "config_file": str(daemon.store.path),
        "config_writable": daemon.store.writable,
        "database": (
            str(database.db_file)
            if isinstance(database, SQLiteDatabaseConfig)
            else "memory"
        ),
        "log_file": str(config.logging.log_file) if config.logging.log_file else None,
        "auth_method": config.auth.method.value,
        "restart_required": daemon.restart_required,
        "user": {"name": user.name, "method": user.method},
        "in_container": Path("/.dockerenv").exists()
        or bool(os.environ.get("KUBERNETES_SERVICE_HOST")),
    }


@router.get("/system/health")
async def health_checks(request: Request) -> list[dict[str, Any]]:
    daemon = _daemon(request)
    return await asyncio.to_thread(
        run_checks,
        daemon.config,
        config_writable=daemon.store.writable,
        has_credentials=daemon.auth.has_credentials,
        skip_readonly_check=daemon.skip_readonly_check,
        restart_required=daemon.restart_required,
        last_scan=daemon.state.get_meta("last_scan"),
    )


@router.get("/dashboard")
async def dashboard(request: Request) -> dict[str, Any]:
    daemon = _daemon(request)
    library_status = await asyncio.to_thread(
        collect_status, daemon.config, daemon.state
    )
    return {**daemon.snapshot(), **library_status}


@router.get("/languages")
async def languages() -> list[dict[str, str]]:
    """ISO 639 languages for the filter editor."""
    return known_languages()


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    dry_run: bool = False
    force: bool = False


@router.post("/scans", status_code=status.HTTP_202_ACCEPTED)
async def queue_scan(
    request: Request, user: User, body: Annotated[ScanRequest | None, Body()] = None
) -> dict[str, Any]:
    body = body or ScanRequest()
    source = "api" if user.method == "api_key" else f"ui:{user.name}"
    await _daemon(request).request_scan(source, dry_run=body.dry_run, force=body.force)
    return {"status": "queued"}


@router.post("/scans/cancel")
async def cancel_scan(request: Request) -> dict[str, bool]:
    return {"cancelled": _daemon(request).cancel_scan()}


@router.get("/scans")
async def list_scans(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    items, total = await asyncio.to_thread(
        _daemon(request).state.list_scans, limit, offset
    )
    return {"items": items, "total": total}


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: int, request: Request) -> dict[str, Any]:
    record = await asyncio.to_thread(_daemon(request).state.get_scan, scan_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return record


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConfigDocument(BaseModel):
    config: dict[str, Any]


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    return _daemon(request).store.document()


@router.post("/config/validate", response_model=None)
async def validate_config(
    body: ConfigDocument, request: Request
) -> dict[str, Any] | JSONResponse:
    try:
        config = _daemon(request).store.validate(body.config)
    except ConfigError as exc:
        return _config_error(exc)
    return {"valid": True, "warnings": config.warnings}


@router.put("/config", response_model=None)
async def save_config(
    body: ConfigDocument,
    request: Request,
    user: User,
    if_match: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | JSONResponse:
    daemon = _daemon(request)
    store = daemon.store
    try:
        config = store.save(body.config, etag=if_match.strip('"') if if_match else None)
    except ConfigError as exc:
        return _config_error(exc)
    except ConfigConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ConfigReadOnlyError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    _LOGGER.info("Configuration saved by '%s'", user.name)
    restart = await daemon.apply_config(config)
    return {**store.document(), "restart_required": restart}


@router.get("/config/export", response_class=PlainTextResponse)
async def export_config(request: Request) -> PlainTextResponse:
    store = _daemon(request).store
    try:
        text = store.export_yaml()
    except OSError:
        text = ""
    return PlainTextResponse(
        text,
        media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{store.path.name}"'},
    )


@router.post("/config/import", response_model=None)
async def import_config(request: Request, user: User) -> dict[str, Any] | JSONResponse:
    daemon = _daemon(request)
    raw = await request.body()
    if len(raw) > 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is too large")
    try:
        config = daemon.store.import_yaml(raw.decode("utf-8", errors="replace"))
    except ConfigError as exc:
        return _config_error(exc)
    except ConfigReadOnlyError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    _LOGGER.info("Configuration restored from a backup by '%s'", user.name)
    restart = await daemon.apply_config(config)
    return {**daemon.store.document(), "restart_required": restart}


# ---------------------------------------------------------------------------
# Helpers for the editors
# ---------------------------------------------------------------------------


def _list_dir(path: Path) -> dict[str, Any]:
    entries = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                with contextlib.suppress(OSError):
                    if entry.is_dir() and not entry.name.startswith("."):
                        entries.append(
                            {"name": entry.name, "path": str(Path(entry.path))}
                        )
    except OSError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Cannot read '{path}': {exc.strerror}"
        ) from exc
    entries.sort(key=lambda e: e["name"].lower())
    parent = str(path.parent) if path.parent != path else None
    return {
        "path": str(path),
        "parent": parent,
        "writable": os.access(path, os.W_OK),
        "entries": entries,
    }


@router.get("/filesystem")
async def browse(path: str = "/") -> dict[str, Any]:
    """List sub directories (for the path pickers)."""
    target = Path(path or "/").expanduser()
    if not target.is_absolute():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Path must be absolute")
    return await asyncio.to_thread(_list_dir, target)


class ConnectionTest(BaseModel):
    kind: str
    config: dict[str, Any] | list[Any]


@router.post("/test")
async def test_connection(body: ConnectionTest, request: Request) -> dict[str, Any]:
    """Check a prober, media server or notification settings before saving."""
    store = _daemon(request).store
    try:
        fragment = store.unmask(body.config)
    except ConfigError as exc:
        return {"ok": False, "message": exc.message}
    ok, message = await connections.test(body.kind, fragment)
    return {"ok": ok, "message": message}


# ---------------------------------------------------------------------------
# Logs and live events
# ---------------------------------------------------------------------------


@router.get("/logs")
async def logs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    level: str = "DEBUG",
) -> list[dict[str, Any]]:
    return _daemon(request).logs.entries(limit=limit, min_level=level)


@router.get("/logs/download", response_class=PlainTextResponse)
async def download_logs(request: Request) -> PlainTextResponse:
    entries = _daemon(request).logs.entries(limit=2000)
    lines = [
        f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e['time']))} "
        f"{e['level']:<8} {e['logger']}: {e['message']}"
        for e in entries
    ]
    return PlainTextResponse(
        "\n".join(lines) + "\n",
        headers={"Content-Disposition": 'attachment; filename="boomarr.log"'},
    )


def _sse(event: dict[str, Any]) -> str:
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


async def _event_stream(daemon: Daemon, request: Request) -> AsyncIterator[str]:
    async with daemon.events.subscribe() as queue:
        yield "retry: 3000\n\n"
        yield _sse(
            {"id": 0, "type": "hello", "time": time.time(), "data": daemon.snapshot()}
        )
        while not await request.is_disconnected() and not daemon.shutting_down:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield _sse(event)


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Server-sent events: scan progress, log lines, config changes."""
    return StreamingResponse(
        _event_stream(_daemon(request), request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
