"""Endpoints kept compatible with Boomarr 1.x (probes, metrics, webhooks)."""

import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from boomarr.metrics import METRICS
from boomarr.web.security import Principal, require_user, resolve_principal

if TYPE_CHECKING:  # pragma: no cover
    from boomarr.daemon import Daemon

_LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["integrations"])
User = Annotated[Principal, Depends(require_user)]


@router.get("/health")
@router.head("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    """Liveness probe, never requires authentication."""
    return {"status": "ok"}


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    """Prometheus metrics (authenticated only if ``server.metrics_auth``)."""
    daemon: Daemon = request.app.state.daemon
    if daemon.config.server.metrics_auth and resolve_principal(request) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")
    return PlainTextResponse(
        METRICS.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )


@router.get("/api/v1/status")
async def legacy_status(request: Request, _: User) -> dict[str, Any]:
    daemon: Daemon = request.app.state.daemon
    return daemon.runner.status()


async def _queue(request: Request, source: str) -> dict[str, str]:
    daemon: Daemon = request.app.state.daemon
    await daemon.request_scan(source)
    peer = request.client.host if request.client else "unknown"
    _LOGGER.info("Scan requested via '%s' from %s", source, peer)
    return {"status": "scan queued"}


@router.post("/api/v1/scan", status_code=status.HTTP_202_ACCEPTED)
async def legacy_scan(request: Request, _: User) -> dict[str, str]:
    return await _queue(request, "api")


@router.post("/api/v1/webhook/{name}", status_code=status.HTTP_202_ACCEPTED)
async def webhook(name: str, request: Request, _: User) -> dict[str, str]:
    """Sonarr/Radarr/Lidarr "Connect → Webhook" target (body is ignored)."""
    return await _queue(request, f"webhook:{name[:32] or 'webhook'}")
