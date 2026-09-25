"""Tests for config validation hardening and new config options."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from boomarr.config import (
    AudioLanguageFilterConfig,
    Config,
    FileExtensionFilterConfig,
    GeneralConfig,
    LanguageEntry,
    LibraryConfig,
    LoggingConfig,
    ScheduleTriggerConfig,
    SymlinkLibraryConfig,
    WebhookTriggerConfig,
    load_config,
)
from boomarr.pipeline import PipelineFactory
from boomarr.triggers.schedule import ScheduleTrigger
from boomarr.triggers.webhook import WebhookTrigger


def _lib(lib_name: str, input_path: str, **sym: Any) -> dict[str, Any]:
    return {
        "name": lib_name,
        "input_path": input_path,
        "symlink_libraries": [
            {"filters": [{"type": "audio_language", "languages": ["deu"]}], **sym}
        ],
    }


def _config(**data: Any) -> Config:
    return Config(
        config_dir=Path("."),
        config_file="test.yml",
        general=GeneralConfig(),
        logging=LoggingConfig(),
        **data,
    )


def _load(tmp_path: Path, data: object) -> Config:
    (tmp_path / "boomarr.yml").write_text(yaml.dump(data), encoding="utf-8")
    return load_config(tmp_path, "boomarr.yml")


class TestPathOverlap:
    def test_path_containing_word_inside_is_accepted(self) -> None:
        """Regression: overlap detection used to match on the error text."""
        cfg = _config(
            output_path="/data/filtered",
            libraries=[_lib("Movies", "/data/inside/movies")],
        )
        assert cfg.libraries[0].input_path == Path("/data/inside/movies")

    def test_output_inside_other_librarys_input_rejected(self) -> None:
        with pytest.raises(ValueError, match="of library 'Media'"):
            _config(
                libraries=[
                    {**_lib("Media", "/media"), "output_path": "/filtered"},
                    {**_lib("Shows", "/shows"), "output_path": "/media/filtered"},
                ]
            )

    def test_duplicate_output_rejected(self) -> None:
        with pytest.raises(ValueError, match="same output directory"):
            _config(
                output_path="/filtered",
                libraries=[
                    _lib("A", "/a", name="German"),
                    _lib("B", "/b", name="German"),
                ],
            )

    def test_nested_outputs_rejected(self) -> None:
        with pytest.raises(ValueError, match="nested"):
            _config(
                libraries=[
                    _lib("A", "/a", output_path="/filtered/de"),
                    _lib("B", "/b", output_path="/filtered/de/more"),
                ],
            )

    def test_explicit_symlink_outputs_need_no_base(self) -> None:
        cfg = _config(libraries=[_lib("A", "/a", output_path="/filtered/de")])
        lib = cfg.libraries[0]
        assert cfg.library_output_base(lib) is None
        assert cfg.symlink_library_output(lib, lib.symlink_libraries[0]) == Path(
            "/filtered/de"
        )

    def test_distinct_outputs_accepted(self) -> None:
        cfg = _config(
            output_path="/filtered",
            libraries=[_lib("Movies", "/movies"), _lib("Shows", "/shows")],
        )
        outs = [
            cfg.symlink_library_output(lib, lib.symlink_libraries[0])
            for lib in cfg.libraries
        ]
        assert outs == [Path("/filtered/movies-deu"), Path("/filtered/shows-deu")]


class TestNames:
    @pytest.mark.parametrize("name", ["a/b", "..", ".", "a\\b"])
    def test_library_name_must_be_single_component(self, name: str) -> None:
        with pytest.raises(ValueError, match="single directory name"):
            LibraryConfig(
                name=name,
                input_path=Path("/in"),
                output_path=Path("/out"),
                symlink_libraries=[
                    SymlinkLibraryConfig(
                        filters=[
                            AudioLanguageFilterConfig(
                                languages=[LanguageEntry(code="deu")]
                            )
                        ]
                    )
                ],
            )

    def test_symlink_library_name_must_be_single_component(self) -> None:
        with pytest.raises(ValueError, match="single directory name"):
            SymlinkLibraryConfig(
                name="../escape",
                filters=[
                    AudioLanguageFilterConfig(languages=[LanguageEntry(code="deu")])
                ],
            )

    def test_suffix_must_be_single_component(self) -> None:
        with pytest.raises(ValueError, match="single directory name"):
            AudioLanguageFilterConfig(
                languages=[LanguageEntry(code="deu")], suffix="a/b"
            )


class TestSuffixStability:
    def test_default_suffix_matches_legacy_naming(self) -> None:
        """Existing output folders must keep their names."""
        cfg = _config(
            output_path="/filtered",
            libraries=[
                {
                    "name": "My Movies",
                    "input_path": "/movies",
                    "symlink_libraries": [
                        {
                            "filters": [
                                {
                                    "type": "audio_language",
                                    "languages": ["ENG", {"code": "deu"}],
                                }
                            ]
                        }
                    ],
                }
            ],
        )
        lib = cfg.libraries[0]
        assert cfg.symlink_library_output(lib, lib.symlink_libraries[0]) == Path(
            "/filtered/my-movies-deu-eng"
        )


class TestExtensions:
    def test_file_extensions_normalised(self) -> None:
        cfg = FileExtensionFilterConfig(extensions=["mkv", ".MP4", " avi "])
        assert cfg.extensions == [".mkv", ".mp4", ".avi"]

    def test_sidecar_extensions_normalised(self) -> None:
        cfg = _config(sidecar_extensions=["SRT", ".ass"])
        assert cfg.sidecar_extensions == [".srt", ".ass"]


class TestLibraryOverrides:
    def test_library_overrides_global_options(self) -> None:
        cfg = _config(
            output_path="/filtered",
            relative_symlinks=True,
            sidecar_extensions=[".srt"],
            libraries=[
                {
                    **_lib("Movies", "/movies"),
                    "relative_symlinks": False,
                    "sidecar_extensions": [],
                    "ignore_patterns": ["extras"],
                },
                _lib("Shows", "/shows"),
            ],
        )
        movies, shows = cfg.libraries
        assert cfg.relative_symlinks_for(movies) is False
        assert cfg.relative_symlinks_for(shows) is True
        assert cfg.sidecar_extensions_for(movies) == frozenset()
        assert cfg.sidecar_extensions_for(shows) == frozenset({".srt"})
        assert cfg.ignore_patterns_for(movies) == ["extras"]
        assert "@eaDir" in cfg.ignore_patterns_for(shows)

    def test_pipeline_receives_options(self) -> None:
        cfg = _config(
            output_path="/filtered",
            probe_workers=7,
            relative_symlinks=True,
            libraries=[_lib("Movies", "/movies")],
        )
        pipeline = PipelineFactory(dry_run=True).for_scan(cfg, cfg.libraries[0])
        assert pipeline.probe_workers == 7
        assert pipeline.relative_symlinks is True
        assert pipeline.symlinks.dry_run is True

    def test_probe_workers_bounds(self) -> None:
        with pytest.raises(ValueError):
            _config(probe_workers=0)


class TestTriggers:
    def test_webhook_trigger_config(self) -> None:
        cfg = _config(
            triggers=[
                {"type": "webhook", "port": 1234, "api_key": "secret"},
                "schedule",
            ]
        )
        webhook, schedule = cfg.triggers
        assert isinstance(webhook, WebhookTriggerConfig)
        assert isinstance(schedule, ScheduleTriggerConfig)
        assert webhook.api_key is not None
        assert webhook.api_key.get_secret_value() == "secret"
        assert "secret" not in cfg.model_dump_json()

        built = PipelineFactory.build_triggers(cfg.triggers)
        assert isinstance(built[0], WebhookTrigger)
        assert isinstance(built[1], ScheduleTrigger)

    def test_empty_api_key_means_none(self) -> None:
        assert WebhookTriggerConfig.model_validate({"api_key": "  "}).api_key is None

    def test_api_key_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEBHOOK_API_KEY", "from-env")
        cfg = WebhookTriggerConfig()
        assert cfg.api_key is not None
        assert cfg.api_key.get_secret_value() == "from-env"
        explicit = WebhookTriggerConfig.model_validate({"api_key": "file"})
        assert explicit.api_key is not None
        assert explicit.api_key.get_secret_value() == "file"

    def test_invalid_port_rejected(self) -> None:
        with pytest.raises(ValueError):
            WebhookTriggerConfig(port=70000)


class TestLoadConfigRobustness:
    def test_unknown_keys_reported(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            {
                "output_path": "/filtered",
                "libaries": [],
                "logging": {"levle": "debug", "dir": "/tmp/x"},
                "libraries": [
                    {
                        **_lib("Movies", "/movies"),
                        "symlink_libraries": [
                            {
                                "filters": [
                                    {
                                        "type": "audio_language",
                                        "languages": ["deu"],
                                        "langauges": ["eng"],
                                    }
                                ]
                            }
                        ],
                    }
                ],
            },
        )
        text = "\n".join(cfg.warnings)
        assert "'libaries'" in text
        assert "'logging.levle'" in text
        assert "'logging.dir' cannot be set" in text
        assert "'libraries[0].symlink_libraries[0].filters[0].langauges'" in text

    def test_valid_config_has_no_warnings(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            {"output_path": "/filtered", "libraries": [_lib("Movies", "/movies")]},
        )
        assert cfg.warnings == []

    @pytest.mark.parametrize("content", ["- a\n- b\n", "just a string\n"])
    def test_non_mapping_top_level_exits(self, tmp_path: Path, content: str) -> None:
        (tmp_path / "boomarr.yml").write_text(content, encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            load_config(tmp_path, "boomarr.yml")
        assert exc.value.code == 1

    def test_invalid_yaml_exits(self, tmp_path: Path) -> None:
        (tmp_path / "boomarr.yml").write_text("a: [unclosed\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_config(tmp_path, "boomarr.yml")

    def test_non_mapping_section_exits(self, tmp_path: Path) -> None:
        (tmp_path / "boomarr.yml").write_text("logging: debug\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_config(tmp_path, "boomarr.yml")

    def test_new_top_level_options_loaded(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            {
                "output_path": "/filtered",
                "probe_workers": 2,
                "relative_symlinks": True,
                "sidecar_extensions": [],
                "ignore_patterns": ["x"],
            },
        )
        assert cfg.probe_workers == 2
        assert cfg.relative_symlinks is True
        assert cfg.sidecar_extensions == []
        assert cfg.ignore_patterns == ["x"]
