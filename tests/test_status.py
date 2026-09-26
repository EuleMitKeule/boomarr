"""Tests for the status command: last scan persistence, collection, rendering."""

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from boomarr.config import (
    AudioLanguageFilterConfig,
    Config,
    GeneralConfig,
    LoggingConfig,
    ResolutionFilterConfig,
)
from boomarr.pipeline import PipelineFactory
from boomarr.runner import LAST_SCAN_KEY, ScanRunner
from boomarr.state import InMemoryStateStore, SQLiteStateStore, StateStore
from boomarr.status import collect_status, render_plain, render_rich


def _config(tmp_path: Path, **extra: Any) -> Config:
    media = tmp_path / "media"
    media.mkdir(exist_ok=True)
    return Config.model_validate(
        {
            "config_dir": tmp_path,
            "config_file": "t.yml",
            "general": GeneralConfig(),
            "logging": LoggingConfig(),
            "output_path": tmp_path / "out",
            "libraries": [
                {
                    "name": "Movies",
                    "input_path": media,
                    "symlink_libraries": [
                        {
                            "filters": [
                                {
                                    "type": "audio_language",
                                    "languages": [
                                        "deu",
                                        {"code": "eng", "aliases": ["und"]},
                                    ],
                                }
                            ]
                        }
                    ],
                },
                {
                    "name": "Gone",
                    "input_path": tmp_path / "missing",
                    "output_path": tmp_path / "out2",
                    "symlink_libraries": [
                        {"filters": [{"type": "resolution", "min_height": "4k"}]}
                    ],
                },
            ],
            **extra,
        }
    )


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_meta_roundtrip(kind: str, tmp_path: Path) -> None:
    store: StateStore = (
        InMemoryStateStore()
        if kind == "memory"
        else SQLiteStateStore(tmp_path / "s.db")
    )
    assert store.get_meta("x") is None
    store.set_meta("x", {"a": 1, "p": Path("/y")})
    store.set_meta("x", {"a": 2})
    assert store.get_meta("x") == {"a": 2}
    store.close()


def test_meta_survives_restart_and_cache_rebuild(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    store = SQLiteStateStore(db)
    store.set_meta(LAST_SCAN_KEY, {"finished_at": 1.0})
    store.close()
    store = SQLiteStateStore(db)
    assert store.get_meta(LAST_SCAN_KEY) == {"finished_at": 1.0}
    store.close()


def test_filter_describe() -> None:
    cfg = AudioLanguageFilterConfig.model_validate(
        {"languages": ["deu", {"code": "eng", "aliases": ["und"]}], "mode": "all"}
    )
    assert cfg.describe() == "audio_language(languages=[deu, eng(+und)], mode=all)"
    inverted = AudioLanguageFilterConfig.model_validate(
        {"languages": ["eng"], "invert": True, "suffix": "x"}
    )
    assert inverted.describe() == "NOT audio_language(languages=[eng])"
    assert (
        ResolutionFilterConfig(min_height=720).describe()
        == "resolution(min_height=720)"
    )


def test_runner_persists_last_scan_but_not_dry_run(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state = InMemoryStateStore()
    ScanRunner(config, PipelineFactory(state=state), dry_run=True).run(
        threading.Event()
    )
    assert state.get_meta(LAST_SCAN_KEY) is None
    ScanRunner(config, PipelineFactory(state=state)).run(threading.Event())
    last = state.get_meta(LAST_SCAN_KEY)
    assert last is not None
    assert last["result"]["errors"] == 1  # the missing library
    assert last["duration_seconds"] >= 0


def test_collect_and_render(tmp_path: Path) -> None:
    config = _config(tmp_path, server={"enabled": True, "port": 1234})
    out = tmp_path / "out" / "movies-deu-eng"
    out.mkdir(parents=True)
    target = tmp_path / "media" / "a.mkv"
    target.touch()
    (out / "a.mkv").symlink_to(target)
    state = InMemoryStateStore()
    state.set_meta(
        LAST_SCAN_KEY,
        {
            "finished_at": 0,
            "duration_seconds": 1.5,
            "error": None,
            "result": {
                "created": 1,
                "removed": 0,
                "probed": 1,
                "errors": 0,
                "blocked": 0,
            },
        },
    )

    data = collect_status(config, state)
    json.dumps(data)
    movies, gone = data["libraries"]
    assert movies["outputs"][0]["links"] == 1
    assert movies["outputs"][0]["filters"] == [
        "audio_language(languages=[deu, eng(+und)])"
    ]
    assert gone["input_available"] is False
    assert gone["outputs"][0]["exists"] is False
    assert data["triggers"] == [
        "schedule (every 600s, on start)",
        "web UI & webhooks :1234 (auth: forms)",
    ]

    plain = render_plain(data)
    assert "Last scan:" in plain and "(1.5s)" in plain
    assert "1 links" in plain
    assert "[INPUT MISSING]" in plain
    assert "(not created yet)" in plain

    console = Console(record=True, width=200, force_terminal=True)
    render_rich(data, console)
    text = console.export_text()
    assert "languages=[deu, eng(+und)]" in text  # brackets are not eaten as markup
    assert "input missing" in text


def test_render_without_last_scan(tmp_path: Path) -> None:
    data = collect_status(_config(tmp_path), InMemoryStateStore())
    assert "never (run 'boomarr scan'" in render_plain(data)
