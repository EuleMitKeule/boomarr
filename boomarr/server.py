"""Built-in HTTP server (health, metrics, scan API and webhooks).

Runs a deliberately tiny HTTP/1.1 server on top of :mod:`asyncio` (no extra
dependencies). It is a :class:`TriggerSource`, so webhook requests feed the
same debounced queue as every other trigger. Supported endpoints:

* ``GET  /health`` – liveness probe, never requires authentication.
* ``GET  /metrics`` – Prometheus metrics (authenticated only if
  ``metrics_auth`` is enabled).
* ``GET  /api/v1/status`` – last scan result as JSON.
* ``POST /api/v1/scan`` – queue a full rescan.
* ``POST /api/v1/webhook/<source>`` – same, meant for Sonarr/Radarr/Lidarr
  "Connect → Webhook" notifications (``<source>`` is only used for logging).

When an API key is configured, requests must provide it via the
``X-Api-Key`` header, the ``apikey`` query parameter, or as the password of
HTTP basic authentication (the field Sonarr/Radarr offer in their webhook
settings).
"""

import asyncio
import base64
import binascii
import contextlib
import hmac
import json
import logging
import time
from collections.abc import Callable, Mapping
from urllib.parse import parse_qs, urlsplit

from boomarr.metrics import METRICS
from boomarr.models import ScanEvent
from boomarr.triggers.base import TriggerSource

_LOGGER = logging.getLogger(__name__)

_MAX_HEADER_BYTES = 16 * 1024
_MAX_BODY_BYTES = 1024 * 1024
_READ_TIMEOUT = 10.0

_REASONS = {
    200: "OK",
    202: "Accepted",
    400: "Bad Request",
    401: "Unauthorized",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    413: "Content Too Large",
    503: "Service Unavailable",
}


class _Text:
    """A plain-text response body (used for Prometheus metrics)."""

    def __init__(self, text: str) -> None:
        self.text = text


_Payload = Mapping[str, object] | _Text


class _HttpError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class HttpServer(TriggerSource):
    """HTTP server; emits a scan event for every authenticated scan request.

    Args:
        host: Interface to bind to.
        port: TCP port to listen on (``0`` picks a free port, for tests).
        api_key: Optional shared secret required for API requests.
        metrics_auth: Require the API key for ``/metrics`` as well.
        status_provider: Callable returning the JSON for ``/api/v1/status``.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        api_key: str | None = None,
        metrics_auth: bool = False,
        status_provider: Callable[[], dict[str, object]] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._api_key = api_key
        self._metrics_auth = metrics_auth
        self._status_provider = status_provider
        self._server: asyncio.Server | None = None
        self._queue: asyncio.Queue[ScanEvent] | None = None

    @property
    def port(self) -> int:
        """Return the bound port (useful when started with port 0)."""
        if self._server is not None and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self._port

    async def start(self, queue: asyncio.Queue[ScanEvent]) -> None:
        """Start listening for webhook requests."""
        self._queue = queue
        self._server = await asyncio.start_server(
            self._handle, host=self._host, port=self._port
        )
        _LOGGER.info(
            "HTTP server listening on http://%s:%d (authentication %s)",
            self._host,
            self.port,
            "enabled" if self._api_key else "DISABLED",
        )
        if not self._api_key:
            _LOGGER.warning(
                "HTTP server has no api_key configured: anyone who can reach "
                "port %d can trigger scans",
                self.port,
            )

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            _LOGGER.debug("HTTP server stopped")

    # ------------------------------------------------------------------

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        status: int
        payload: _Payload
        try:
            try:
                status, payload = await asyncio.wait_for(
                    self._process(reader, peer), timeout=_READ_TIMEOUT
                )
            except TimeoutError:
                status, payload = 408, {"error": _REASONS[408]}
            except _HttpError as exc:
                status, payload = exc.status, {"error": exc.message}
            await self._respond(writer, status, payload)
        except (ConnectionError, OSError) as exc:
            _LOGGER.debug("Webhook connection from %s failed: %s", peer, exc)
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()

    async def _process(
        self, reader: asyncio.StreamReader, peer: object
    ) -> tuple[int, _Payload]:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except asyncio.LimitOverrunError as exc:
            raise _HttpError(413, "Headers too large") from exc
        except asyncio.IncompleteReadError as exc:
            raise _HttpError(400, "Incomplete request") from exc
        if len(head) > _MAX_HEADER_BYTES:
            raise _HttpError(413, "Headers too large")

        try:
            request_line, *header_lines = head.decode("latin-1").split("\r\n")
            method, target, _version = request_line.split(" ", 2)
        except ValueError as exc:
            raise _HttpError(400, "Malformed request line") from exc

        headers: dict[str, str] = {}
        for line in header_lines:
            if not line:
                continue
            name, sep, value = line.partition(":")
            if not sep:
                raise _HttpError(400, "Malformed header")
            headers[name.strip().lower()] = value.strip()

        await self._discard_body(reader, headers)

        url = urlsplit(target)
        path = url.path.rstrip("/") or "/"

        if path == "/health":
            if method not in {"GET", "HEAD"}:
                raise _HttpError(405, "Use GET")
            return 200, {"status": "ok"}

        if path == "/metrics":
            if method not in {"GET", "HEAD"}:
                raise _HttpError(405, "Use GET")
            if self._metrics_auth and not self._authorized(headers, url.query):
                raise _HttpError(401, "Invalid or missing API key")
            return 200, _Text(METRICS.render())

        if path == "/api/v1/status":
            if method != "GET":
                raise _HttpError(405, "Use GET")
            if not self._authorized(headers, url.query):
                raise _HttpError(401, "Invalid or missing API key")
            return 200, self._status_provider() if self._status_provider else {}

        source: str | None = None
        if path == "/api/v1/scan":
            source = "api"
        elif path.startswith("/api/v1/webhook/") and path.count("/") == 4:
            source = path.rsplit("/", 1)[1][:32] or "webhook"
        if source is None:
            raise _HttpError(404, "Not found")
        if method != "POST":
            raise _HttpError(405, "Use POST")
        if not self._authorized(headers, url.query):
            _LOGGER.warning("Rejected unauthenticated webhook request from %s", peer)
            raise _HttpError(401, "Invalid or missing API key")

        if self._queue is None:  # pragma: no cover - start() sets it
            raise _HttpError(503, "Not ready")
        await self._queue.put(
            ScanEvent(source=f"webhook:{source}", timestamp=time.monotonic())
        )
        _LOGGER.info("Scan requested via webhook '%s' from %s", source, peer)
        return 202, {"status": "scan queued"}

    async def _discard_body(
        self, reader: asyncio.StreamReader, headers: dict[str, str]
    ) -> None:
        if "chunked" in headers.get("transfer-encoding", "").lower():
            raise _HttpError(400, "Chunked requests are not supported")
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError as exc:
            raise _HttpError(400, "Invalid Content-Length") from exc
        if length < 0:
            raise _HttpError(400, "Invalid Content-Length")
        if length > _MAX_BODY_BYTES:
            raise _HttpError(413, "Body too large")
        if length:
            try:
                await reader.readexactly(length)
            except asyncio.IncompleteReadError as exc:
                raise _HttpError(400, "Incomplete body") from exc

    def _authorized(self, headers: dict[str, str], query: str) -> bool:
        if not self._api_key:
            return True
        candidates: list[str] = []
        if "x-api-key" in headers:
            candidates.append(headers["x-api-key"])
        candidates.extend(parse_qs(query).get("apikey", []))
        auth = headers.get("authorization", "")
        scheme, _, credentials = auth.partition(" ")
        if scheme.lower() == "basic":
            try:
                decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
            except binascii.Error, UnicodeDecodeError:
                decoded = ""
            candidates.append(decoded.partition(":")[2])
        elif scheme.lower() == "bearer":
            candidates.append(credentials)
        expected = self._api_key.encode("utf-8")
        return any(hmac.compare_digest(c.encode("utf-8"), expected) for c in candidates)

    @staticmethod
    async def _respond(
        writer: asyncio.StreamWriter, status: int, payload: _Payload
    ) -> None:
        if isinstance(payload, _Text):
            body = payload.text.encode("utf-8")
            content_type = "text/plain; version=0.0.4; charset=utf-8"
        else:
            body = json.dumps(payload, default=str).encode("utf-8")
            content_type = "application/json"
        head = (
            f"HTTP/1.1 {status} {_REASONS.get(status, 'Error')}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("latin-1")
        writer.write(head + body)
        await writer.drain()
