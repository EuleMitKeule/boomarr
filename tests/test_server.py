"""Tests for the HTTP webhook trigger."""

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable

import pytest

from boomarr.models import ScanEvent
from boomarr.server import HttpServer

Request = Callable[..., Awaitable[tuple[int, dict[str, object]]]]


async def _request(
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    raw: bytes | None = None,
) -> tuple[int, dict[str, object]]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    if raw is None:
        lines = [f"{method} {path} HTTP/1.1", "Host: test"]
        lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
        if body:
            lines.append(f"Content-Length: {len(body)}")
        raw = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    writer.write(raw)
    await writer.drain()
    response = await reader.read()
    writer.close()
    head, _, payload = response.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    return status, json.loads(payload)


def _run(
    api_key: str | None,
    scenario: Callable[[int, asyncio.Queue[ScanEvent]], Awaitable[None]],
) -> None:
    async def main() -> None:
        queue: asyncio.Queue[ScanEvent] = asyncio.Queue()
        trigger = HttpServer(host="127.0.0.1", port=0, api_key=api_key)
        await trigger.start(queue)
        try:
            await scenario(trigger.port, queue)
        finally:
            await trigger.stop()
            await trigger.stop()  # idempotent

    asyncio.run(main())


def test_health_needs_no_auth() -> None:
    async def scenario(port: int, queue: asyncio.Queue[ScanEvent]) -> None:
        assert await _request(port, "GET", "/health") == (200, {"status": "ok"})
        assert queue.empty()

    _run("secret", scenario)


def test_scan_without_api_key_configured() -> None:
    async def scenario(port: int, queue: asyncio.Queue[ScanEvent]) -> None:
        status, _ = await _request(port, "POST", "/api/v1/scan")
        assert status == 202
        event = queue.get_nowait()
        assert event.source == "webhook:api"

    _run(None, scenario)


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/api/v1/scan", {"X-Api-Key": "secret"}),
        ("/api/v1/scan?apikey=secret", {}),
        ("/api/v1/webhook/sonarr", {"Authorization": "Bearer secret"}),
        (
            "/api/v1/webhook/radarr",
            {"Authorization": "Basic " + base64.b64encode(b"user:secret").decode()},
        ),
    ],
)
def test_authenticated_requests_queue_scan(path: str, headers: dict[str, str]) -> None:
    async def scenario(port: int, queue: asyncio.Queue[ScanEvent]) -> None:
        body = json.dumps({"eventType": "Download"}).encode()
        status, payload = await _request(port, "POST", path, headers, body)
        assert status == 202, payload
        assert queue.qsize() == 1

    _run("secret", scenario)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Api-Key": "wrong"},
        {"Authorization": "Basic !!!notbase64"},
        {"Authorization": "Basic " + base64.b64encode(b"secret:").decode()},
    ],
)
def test_unauthenticated_requests_rejected(headers: dict[str, str]) -> None:
    async def scenario(port: int, queue: asyncio.Queue[ScanEvent]) -> None:
        status, _ = await _request(port, "POST", "/api/v1/scan", headers)
        assert status == 401
        assert queue.empty()

    _run("secret", scenario)


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/v1/scan", 405),
        ("POST", "/health", 405),
        ("POST", "/nope", 404),
        ("POST", "/api/v1/webhook/a/b", 404),
    ],
)
def test_routing_errors(method: str, path: str, expected: int) -> None:
    async def scenario(port: int, queue: asyncio.Queue[ScanEvent]) -> None:
        status, _ = await _request(port, method, path)
        assert status == expected
        assert queue.empty()

    _run(None, scenario)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"garbage\r\n\r\n", 400),
        (b"POST /api/v1/scan HTTP/1.1\r\nbadheader\r\n\r\n", 400),
        (b"POST /api/v1/scan HTTP/1.1\r\nContent-Length: abc\r\n\r\n", 400),
        (b"POST /api/v1/scan HTTP/1.1\r\nContent-Length: 99999999\r\n\r\n", 413),
        (b"POST /api/v1/scan HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n", 400),
        (b"POST /api/v1/scan HTTP/1.1\r\nX: " + b"a" * 20000 + b"\r\n\r\n", 413),
    ],
)
def test_malformed_requests(raw: bytes, expected: int) -> None:
    async def scenario(port: int, queue: asyncio.Queue[ScanEvent]) -> None:
        status, _ = await _request(port, "", "", raw=raw)
        assert status == expected
        assert queue.empty()

    _run(None, scenario)


def test_slow_client_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("boomarr.server._READ_TIMEOUT", 0.2)

    async def scenario(port: int, queue: asyncio.Queue[ScanEvent]) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"POST /api/v1/scan HTTP/1.1\r\n")  # never finishes
        await writer.drain()
        response = await reader.read()
        writer.close()
        assert response.startswith(b"HTTP/1.1 408")
        assert queue.empty()

    _run(None, scenario)
