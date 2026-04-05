"""Tests for LibraryConfig validation and loading."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from boomarr.config import LibraryConfig, load_config


class TestLibraryConfig:
    """Tests for LibraryConfig validation."""

    def test_valid_library(self) -> None:
        lib = LibraryConfig(
            name="Movies",
            input_path=Path("/media/movies"),
            output_path=Path("/filtered/movies"),
            languages=["de", "en"],
        )
        assert lib.name == "Movies"
        assert lib.languages == ["de", "en"]

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="empty"):
            LibraryConfig(
                name="  ",
                input_path=Path("/media"),
                output_path=Path("/out"),
                languages=["en"],
            )

    def test_empty_languages_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one"):
            LibraryConfig(
                name="Movies",
                input_path=Path("/media"),
                output_path=Path("/out"),
                languages=[],
            )

    def test_languages_lowercased(self) -> None:
        lib = LibraryConfig(
            name="Movies",
            input_path=Path("/media"),
            output_path=Path("/out"),
            languages=["DE", "En"],
        )
        assert lib.languages == ["de", "en"]

    def test_paths_resolved_to_absolute(self) -> None:
        lib = LibraryConfig(
            name="Movies",
            input_path=Path("media"),
            output_path=Path("out"),
            languages=["en"],
        )
        assert lib.input_path.is_absolute()
        assert lib.output_path.is_absolute()

    def test_name_stripped(self) -> None:
        lib = LibraryConfig(
            name="  Movies  ",
            input_path=Path("/media"),
            output_path=Path("/out"),
            languages=["en"],
        )
        assert lib.name == "Movies"


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
                    "languages": ["de", "en"],
                }
            ]
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        config = load_config(tmp_path, "boomarr.yml")
        assert len(config.libraries) == 1
        assert config.libraries[0].name == "Movies"
        assert config.libraries[0].languages == ["de", "en"]

    def test_multiple_libraries(self, tmp_path: Path) -> None:
        config_file = tmp_path / "boomarr.yml"
        data = {
            "libraries": [
                {
                    "name": "Movies",
                    "input_path": "/media/movies",
                    "output_path": "/filtered/movies",
                    "languages": ["de"],
                },
                {
                    "name": "Shows",
                    "input_path": "/media/shows",
                    "output_path": "/filtered/shows",
                    "languages": ["en"],
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
                    "languages": ["de"],
                },
                {
                    "name": "Movies",
                    "input_path": "/media/movies2",
                    "output_path": "/filtered/movies2",
                    "languages": ["en"],
                },
            ]
        }
        config_file.write_text(yaml.dump(data), encoding="utf-8")
        with pytest.raises(SystemExit):
            load_config(tmp_path, "boomarr.yml")
