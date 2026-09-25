"""Tests for the Sonarr/Radarr prober."""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from boomarr.config import PathMapping, RadarrProberConfig
from boomarr.languages import language_from_name_or_code
from boomarr.pipeline import PipelineFactory
from boomarr.probers.arr import ArrProber, _parse_channels, media_info_from_arr

MOVIES: list[dict[str, Any]] = [
    {
        "id": 1,
        "movieFile": {
            "path": "/movies/Film A/Film A.mkv",
            "mediaInfo": {
                "audioLanguages": "ger/eng/eng",
                "audioCodec": "TrueHD",
                "audioChannels": 7.1,
                "videoCodec": "x265",
                "resolution": "3840x1600",
            },
        },
    },
    {
        "id": 2,
        "movieFile": {
            "path": "/movies/Film B/Film B.mkv",
            "mediaInfo": {"audioLanguages": "English / French"},
        },
    },
    {"id": 3},  # no file
    {
        "id": 4,
        "movieFile": {"path": "/movies/C.mkv", "mediaInfo": {"audioLanguages": ""}},
    },
]

SERIES = [{"id": 7}, {"id": 8}]
EPISODE_FILES = {
    "7": [{"path": "/tv/Show/S01E01.mkv", "mediaInfo": {"audioLanguages": "German"}}],
    "8": [{"path": "/tv/Other/S01E01.mkv", "mediaInfo": {"audioLanguages": "jpn"}}],
}


class _Arr(BaseHTTPRequestHandler):
    calls: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        type(self).calls.append(self.path)
        if self.headers.get("X-Api-Key") != "key":
            self.send_response(401)
            self.end_headers()
            return
        path, _, query = self.path.partition("?")
        body: object
        if path == "/api/v3/movie":
            body = MOVIES
        elif path == "/api/v3/series":
            body = SERIES
        elif path == "/api/v3/episodefile":
            body = EPISODE_FILES[query.split("=")[1]]
        elif path == "/api/v3/system/status":
            body = {"version": "5"}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def arr_url() -> Iterator[str]:
    _Arr.calls = []
    httpd = HTTPServer(("127.0.0.1", 0), _Arr)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_language_names_and_codes() -> None:
    assert language_from_name_or_code("German") == "deu"
    assert language_from_name_or_code("ger") == "deu"
    assert language_from_name_or_code("Portuguese (Brazil)") == "por"
    assert language_from_name_or_code("nonsense words") is None


@pytest.mark.parametrize(
    ("raw", "expected"), [(7.1, 8), (5.1, 6), (2, 2), ("x", None), (0, None)]
)
def test_parse_channels(raw: object, expected: int | None) -> None:
    assert _parse_channels(raw) == expected


def test_media_info_from_arr() -> None:
    info = media_info_from_arr(Path("/m.mkv"), MOVIES[0]["movieFile"]["mediaInfo"])
    assert info is not None
    assert [t.language for t in info.audio_tracks] == ["deu", "eng"]
    assert info.audio_tracks[0].channels == 8
    assert info.audio_tracks[0].codec == "truehd"
    assert info.height == 1600
    assert media_info_from_arr(Path("/m.mkv"), {"audioLanguages": ""}) is None


def test_radarr_lookup_with_path_mapping(arr_url: str) -> None:
    prober = ArrProber(
        kind="radarr",
        url=arr_url,
        api_key="key",
        path_mappings=[PathMapping(local=Path("/data/movies"), remote="/movies")],
    )
    a = prober.probe(Path("/data/movies/Film A/Film A.mkv"))
    b = prober.probe(Path("/data/movies/Film B/Film B.mkv"))
    assert a is not None and [t.language for t in a.audio_tracks] == ["deu", "eng"]
    assert b is not None and [t.language for t in b.audio_tracks] == ["eng", "fra"]
    assert prober.probe(Path("/data/movies/C.mkv")) is None  # empty -> fall back
    assert prober.probe(Path("/data/movies/unknown.mkv")) is None
    assert _Arr.calls.count("/api/v3/movie") == 1  # cached index


def test_sonarr_lookup(arr_url: str) -> None:
    prober = ArrProber(kind="sonarr", url=arr_url, api_key="key")
    info = prober.probe(Path("/tv/Show/S01E01.mkv"))
    assert info is not None and info.audio_tracks[0].language == "deu"
    other = prober.probe(Path("/tv/Other/S01E01.mkv"))
    assert other is not None and other.audio_tracks[0].language == "jpn"


def test_unreachable_server_falls_back(arr_url: str) -> None:
    prober = ArrProber(kind="radarr", url=arr_url, api_key="wrong")
    assert prober.probe(Path("/movies/Film A/Film A.mkv")) is None
    assert prober.probe(Path("/movies/Film B/Film B.mkv")) is None
    assert _Arr.calls.count("/api/v3/movie") == 1  # no retry storm
    assert prober.check_available() is None


def test_config_and_pipeline_reuse(arr_url: str) -> None:
    cfg = RadarrProberConfig.model_validate({"url": arr_url + "/", "api_key": "key"})
    factory = PipelineFactory()
    first = factory._cached_probers([cfg])
    second = factory._cached_probers([cfg])
    assert first is second
    assert isinstance(first[0], ArrProber)
    with pytest.raises(ValueError, match="http"):
        RadarrProberConfig.model_validate({"url": "radarr:7878", "api_key": "k"})
