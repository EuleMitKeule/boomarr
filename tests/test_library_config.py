"""Tests for LibraryConfig validation and loading."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from boomarr.config import (
    AudioLanguageFilterConfig,
    FFProbeProberConfig,
    FileExtensionFilterConfig,
    LibraryConfig,
    PostProbeFilterType,
    PreProbeFilterType,
    ProberType,
    SymlinkLibraryConfig,
    load_config,
)


def _sym_lib(languages: list[str] | None = None) -> SymlinkLibraryConfig:
    """Build a minimal SymlinkLibraryConfig for testing."""
    return SymlinkLibraryConfig(
        filters=[
            AudioLanguageFilterConfig(
                languages=languages or ["de"],
            ),
        ],
    )


class TestLibraryConfig:
    """Tests for LibraryConfig validation."""

    def test_valid_library(self) -> None:
        lib = LibraryConfig(
            name="Movies",
            input_path=Path("/media/movies"),
            output_path=Path("/filtered/movies"),
            symlink_libraries=[_sym_lib(["de", "en"])],
        )
        assert lib.name == "Movies"
        assert len(lib.symlink_libraries) == 1

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="empty"):
            LibraryConfig(
                name="  ",
                input_path=Path("/media"),
                output_path=Path("/out"),
                symlink_libraries=[_sym_lib()],
            )

    def test_empty_symlink_libraries_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one"):
            LibraryConfig(
                name="Movies",
                input_path=Path("/media"),
                output_path=Path("/out"),
                symlink_libraries=[],
            )

    def test_empty_filters_in_symlink_library_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one filter"):
            LibraryConfig(
                name="Movies",
                input_path=Path("/media"),
                output_path=Path("/out"),
                symlink_libraries=[SymlinkLibraryConfig(filters=[])],
            )

    def test_paths_resolved_to_absolute(self) -> None:
        lib = LibraryConfig(
            name="Movies",
            input_path=Path("media"),
            output_path=Path("out"),
            symlink_libraries=[_sym_lib()],
        )
        assert lib.input_path.is_absolute()
        assert lib.output_path.is_absolute()

    def test_name_stripped(self) -> None:
        lib = LibraryConfig(
            name="  Movies  ",
            input_path=Path("/media"),
            output_path=Path("/out"),
            symlink_libraries=[_sym_lib()],
        )
        assert lib.name == "Movies"

    def test_symlink_library_output_path_resolved(self) -> None:
        lib = LibraryConfig(
            name="Movies",
            input_path=Path("/media"),
            output_path=Path("/out"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                    output_path=Path("custom_output"),
                ),
            ],
        )
        assert lib.symlink_libraries[0].output_path is not None
        assert lib.symlink_libraries[0].output_path.is_absolute()

    def test_symlink_library_output_path_none_stays_none(self) -> None:
        """Explicitly passing output_path=None should keep it None (line 270)."""
        sym = SymlinkLibraryConfig(
            output_path=None,
            filters=[AudioLanguageFilterConfig(languages=["de"])],
        )
        assert sym.output_path is None


class TestPostProbeFilterConfig:
    """Tests for PostProbeFilterConfig and AudioLanguageFilterConfig."""

    def test_audio_language_fields_stored(self) -> None:
        config = AudioLanguageFilterConfig(languages=["de", "en"])
        assert config.type == PostProbeFilterType.AUDIO_LANGUAGE
        assert config.languages == ["de", "en"]

    def test_suffix_optional(self) -> None:
        config = AudioLanguageFilterConfig(languages=["de"])
        assert config.suffix is None

    def test_suffix_set(self) -> None:
        config = AudioLanguageFilterConfig(languages=["de"], suffix="german")
        assert config.suffix == "german"

    def test_audio_language_requires_at_least_one_language(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="at least one language"):
            AudioLanguageFilterConfig(languages=[])

    def test_audio_language_shorthand_coercion_via_yaml(self, tmp_path: Path) -> None:
        """Verify string shorthand works through YAML loading for pre-probe filters."""
        import yaml

        from boomarr.config import load_config

        config_file = tmp_path / "boomarr.yml"
        data = {"pre_probe_filters": ["file_extension"]}
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        config = load_config(tmp_path, "boomarr.yml")
        assert config.pre_probe_filters == [FileExtensionFilterConfig()]

    def test_symlink_library_name_stored(self) -> None:
        lib = SymlinkLibraryConfig(
            name="german",
            filters=[AudioLanguageFilterConfig(languages=["de"])],
        )
        assert lib.name == "german"

    def test_enum_values_are_strings(self) -> None:
        assert str(ProberType.FFPROBE) == "ffprobe"
        assert str(PreProbeFilterType.FILE_EXTENSION) == "file_extension"
        assert str(PostProbeFilterType.AUDIO_LANGUAGE) == "audio_language"

    def test_invalid_prober_type_rejected(self) -> None:
        from boomarr.config import ProberConfig

        with pytest.raises(ValidationError):
            ProberConfig(type="nonexistent")  # type: ignore[arg-type]

    def test_invalid_post_probe_filter_type_rejected(self) -> None:
        from boomarr.config import PostProbeFilterConfig

        with pytest.raises(ValidationError):
            PostProbeFilterConfig(type="nonexistent")  # type: ignore[arg-type]


class TestConfigLibraries:
    """Tests for libraries in the root Config."""

    def test_empty_libraries_default(self, tmp_path: Path) -> None:
        config_file = tmp_path / "boomarr.yml"
        config_file.touch()
        config = load_config(tmp_path, "boomarr.yml")
        assert config.libraries == []

    def test_libraries_loaded_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "boomarr.yml"
        data = {
            "libraries": [
                {
                    "name": "Movies",
                    "input_path": "/media/movies",
                    "output_path": "/filtered/movies",
                    "symlink_libraries": [
                        {
                            "filters": [
                                {
                                    "type": "audio_language",
                                    "languages": ["de", "en"],
                                },
                            ],
                        },
                    ],
                }
            ]
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        config = load_config(tmp_path, "boomarr.yml")
        assert len(config.libraries) == 1
        assert config.libraries[0].name == "Movies"
        assert len(config.libraries[0].symlink_libraries) == 1

    def test_multiple_libraries(self, tmp_path: Path) -> None:
        config_file = tmp_path / "boomarr.yml"
        data = {
            "libraries": [
                {
                    "name": "Movies",
                    "input_path": "/media/movies",
                    "output_path": "/filtered/movies",
                    "symlink_libraries": [
                        {
                            "filters": [
                                {
                                    "type": "audio_language",
                                    "languages": ["de"],
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "Shows",
                    "input_path": "/media/shows",
                    "output_path": "/filtered/shows",
                    "symlink_libraries": [
                        {
                            "filters": [
                                {
                                    "type": "audio_language",
                                    "languages": ["en"],
                                },
                            ],
                        },
                    ],
                },
            ]
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        config = load_config(tmp_path, "boomarr.yml")
        assert len(config.libraries) == 2

    def test_duplicate_library_names_rejected(self, tmp_path: Path) -> None:
        config_file = tmp_path / "boomarr.yml"
        data = {
            "libraries": [
                {
                    "name": "Movies",
                    "input_path": "/media/movies",
                    "output_path": "/filtered/movies",
                    "symlink_libraries": [
                        {
                            "filters": [
                                {
                                    "type": "audio_language",
                                    "languages": ["de"],
                                },
                            ],
                        },
                    ],
                },
                {
                    "name": "Movies",
                    "input_path": "/media/movies2",
                    "output_path": "/filtered/movies2",
                    "symlink_libraries": [
                        {
                            "filters": [
                                {
                                    "type": "audio_language",
                                    "languages": ["en"],
                                },
                            ],
                        },
                    ],
                },
            ]
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with pytest.raises(SystemExit):
            load_config(tmp_path, "boomarr.yml")

    def test_global_probers_loaded_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "boomarr.yml"
        data = {"probers": ["ffprobe"]}
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        config = load_config(tmp_path, "boomarr.yml")
        assert config.probers == [FFProbeProberConfig()]

    def test_global_pre_probe_filters_loaded_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "boomarr.yml"
        data = {"pre_probe_filters": ["file_extension"]}
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        config = load_config(tmp_path, "boomarr.yml")
        assert config.pre_probe_filters == [FileExtensionFilterConfig()]

    def test_global_probers_default(self, tmp_path: Path) -> None:
        config_file = tmp_path / "boomarr.yml"
        config_file.touch()
        config = load_config(tmp_path, "boomarr.yml")
        assert config.probers == [FFProbeProberConfig()]

    def test_global_pre_probe_filters_default(self, tmp_path: Path) -> None:
        config_file = tmp_path / "boomarr.yml"
        config_file.touch()
        config = load_config(tmp_path, "boomarr.yml")
        assert config.pre_probe_filters == [FileExtensionFilterConfig()]
