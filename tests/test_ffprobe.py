"""Tests for the FFprobe prober implementation."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from boomarr.models import AudioTrack
from boomarr.probers.ffprobe import FFProbeProber, _extract_audio_tracks

# -- Sample ffprobe JSON payloads ------------------------------------------------

FFPROBE_TWO_AUDIO = json.dumps(
    {
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "tags": {},
            },
            {
                "index": 1,
                "codec_name": "aac",
                "codec_type": "audio",
                "tags": {"language": "eng", "title": "English Stereo"},
            },
            {
                "index": 2,
                "codec_name": "ac3",
                "codec_type": "audio",
                "tags": {"language": "de"},
            },
        ]
    }
)

FFPROBE_NO_LANGUAGE_TAG = json.dumps(
    {
        "streams": [
            {
                "index": 0,
                "codec_name": "aac",
                "codec_type": "audio",
                "tags": {},
            },
        ]
    }
)

FFPROBE_NO_TAGS = json.dumps(
    {
        "streams": [
            {
                "index": 0,
                "codec_name": "flac",
                "codec_type": "audio",
            },
        ]
    }
)

FFPROBE_NO_AUDIO = json.dumps(
    {
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "tags": {},
            },
        ]
    }
)

FFPROBE_EMPTY = json.dumps({"streams": []})


# -- _extract_audio_tracks unit tests -------------------------------------------


class TestExtractAudioTracks:
    def test_two_audio_streams(self) -> None:
        tracks = _extract_audio_tracks(json.loads(FFPROBE_TWO_AUDIO))
        assert len(tracks) == 2
        assert tracks[0] == AudioTrack(
            index=1, language="eng", codec="aac", title="English Stereo"
        )
        assert tracks[1] == AudioTrack(index=2, language="de", codec="ac3", title=None)

    def test_missing_language_defaults_to_und(self) -> None:
        tracks = _extract_audio_tracks(json.loads(FFPROBE_NO_LANGUAGE_TAG))
        assert len(tracks) == 1
        assert tracks[0].language == "und"

    def test_missing_tags_defaults_to_und(self) -> None:
        tracks = _extract_audio_tracks(json.loads(FFPROBE_NO_TAGS))
        assert len(tracks) == 1
        assert tracks[0].language == "und"
        assert tracks[0].codec == "flac"

    def test_no_audio_streams(self) -> None:
        tracks = _extract_audio_tracks(json.loads(FFPROBE_NO_AUDIO))
        assert tracks == []

    def test_empty_streams(self) -> None:
        tracks = _extract_audio_tracks(json.loads(FFPROBE_EMPTY))
        assert tracks == []

    def test_missing_streams_key(self) -> None:
        tracks = _extract_audio_tracks({})
        assert tracks == []


# -- FFProbeProber.probe() integration tests (subprocess mocked) ----------------


def _mock_run_ok(stdout: str) -> subprocess.CompletedProcess[str]:
    """Return a mock CompletedProcess with the given stdout."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


class TestFFProbeProber:
    def test_probe_extracts_audio_tracks(self, tmp_path: Path) -> None:
        video = tmp_path / "movie.mkv"
        video.write_bytes(b"\x00" * 64)

        with patch("boomarr.probers.ffprobe.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run_ok(FFPROBE_TWO_AUDIO)
            info = FFProbeProber().probe(video)

        assert info is not None
        assert len(info.audio_tracks) == 2
        assert info.audio_tracks[0].language == "eng"
        assert info.audio_tracks[1].language == "de"
        assert info.size == 64

    def test_probe_missing_language(self, tmp_path: Path) -> None:
        video = tmp_path / "movie.mkv"
        video.write_bytes(b"\x00")

        with patch("boomarr.probers.ffprobe.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run_ok(FFPROBE_NO_TAGS)
            info = FFProbeProber().probe(video)

        assert info is not None
        assert info.audio_tracks[0].language == "und"

    def test_probe_nonexistent_file(self, tmp_path: Path) -> None:
        info = FFProbeProber().probe(tmp_path / "nope.mkv")
        assert info is None

    def test_probe_ffprobe_returns_error(self, tmp_path: Path) -> None:
        video = tmp_path / "bad.mkv"
        video.write_bytes(b"\x00")

        with patch("boomarr.probers.ffprobe.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="Invalid data"
            )
            info = FFProbeProber().probe(video)

        assert info is None

    def test_probe_ffprobe_timeout(self, tmp_path: Path) -> None:
        video = tmp_path / "slow.mkv"
        video.write_bytes(b"\x00")

        with patch("boomarr.probers.ffprobe.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)
            info = FFProbeProber().probe(video)

        assert info is None

    def test_probe_ffprobe_not_found(self, tmp_path: Path) -> None:
        video = tmp_path / "movie.mkv"
        video.write_bytes(b"\x00")

        with patch("boomarr.probers.ffprobe.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("ffprobe not found")
            info = FFProbeProber().probe(video)

        assert info is None

    def test_probe_invalid_json(self, tmp_path: Path) -> None:
        video = tmp_path / "movie.mkv"
        video.write_bytes(b"\x00")

        with patch("boomarr.probers.ffprobe.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run_ok("not json at all")
            info = FFProbeProber().probe(video)

        assert info is None

    def test_probe_no_audio_returns_empty_tracks(self, tmp_path: Path) -> None:
        video = tmp_path / "silent.mkv"
        video.write_bytes(b"\x00")

        with patch("boomarr.probers.ffprobe.subprocess.run") as mock_run:
            mock_run.return_value = _mock_run_ok(FFPROBE_NO_AUDIO)
            info = FFProbeProber().probe(video)

        assert info is not None
        assert info.audio_tracks == []
