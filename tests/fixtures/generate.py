#!/usr/bin/env python3
"""Generates fixture media files for Boomarr tests and development.

Creates minimal but valid MKV files using FFmpeg, covering all audio-language
test scenarios. Safe to re-run — existing files are overwritten.

Requires: ffmpeg on PATH.

Usage:
    python tests/fixtures/generate.py
    uv run python tests/fixtures/generate.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent
MEDIA_DIR = FIXTURES_DIR / "media"

# Output duration for each synthetic sample.
# Keep short so files stay tiny enough to commit.
_DURATION = "1"

# Low sample rate + bitrate for minimum file size without breaking AAC.
_SAMPLE_RATE = 8000
_BITRATE = "8k"

# (path relative to MEDIA_DIR, list of ISO 639-2 language codes)
# Empty list → no audio tracks (video-only MKV).
_MEDIA_SPECS: list[tuple[str, list[str]]] = [
    ("movies/Sample.Movie.DE.mkv", ["deu"]),
    ("movies/Sample.Movie.EN.mkv", ["eng"]),
    ("movies/Sample.Movie.DE.EN.mkv", ["deu", "eng"]),
    ("movies/Sample.Movie.DE.EN.FR.mkv", ["deu", "eng", "fra"]),
    ("movies/Sample.Movie.NoAudio.mkv", []),
    ("shows/Sample.Show/S01E01.DE.mkv", ["deu"]),
    ("shows/Sample.Show/S01E02.EN.mkv", ["eng"]),
    ("shows/Sample.Show/S01E03.DE.EN.mkv", ["deu", "eng"]),
]

# (path relative to MEDIA_DIR, text content)
_NON_MEDIA_SPECS: list[tuple[str, str]] = [
    ("non_media/poster.jpg", "stub:not-a-real-image\n"),
    ("non_media/info.nfo", "<nfo><title>Sample</title></nfo>\n"),
    (
        "non_media/subtitle.en.srt",
        "1\n00:00:00,000 --> 00:00:01,000\nSample subtitle\n",
    ),
]


def _build_audio_cmd(output: Path, languages: list[str]) -> list[str]:
    """Build an ffmpeg command for an MKV with N silent audio tracks."""
    # One lavfi anullsrc input per audio track.
    inputs: list[str] = []
    for _ in languages:
        inputs += ["-f", "lavfi", "-i", f"anullsrc=r={_SAMPLE_RATE}:cl=mono"]

    # Map each input, encode as AAC, tag language per stream.
    maps: list[str] = []
    for i in range(len(languages)):
        maps += ["-map", str(i)]

    metadata: list[str] = []
    for i, lang in enumerate(languages):
        metadata += [f"-metadata:s:a:{i}", f"language={lang}"]

    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        *inputs,
        "-t",
        _DURATION,
        *maps,
        "-c:a",
        "aac",
        "-b:a",
        _BITRATE,
        *metadata,
        str(output),
    ]


def _build_video_only_cmd(output: Path) -> list[str]:
    """Build an ffmpeg command for an MKV with a tiny video stream and no audio."""
    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=black:s=2x2:r=1",
        "-t",
        _DURATION,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "51",
        "-an",
        str(output),
    ]


def _make_mkv(output: Path, languages: list[str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = (
        _build_audio_cmd(output, languages)
        if languages
        else _build_video_only_cmd(output)
    )
    subprocess.run(cmd, check=True)
    size = output.stat().st_size
    rel = output.relative_to(FIXTURES_DIR)
    print(f"  [{size:>6} B]  {rel}  (langs={languages or 'none'})")


def _make_stub(output: Path, content: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    size = output.stat().st_size
    rel = output.relative_to(FIXTURES_DIR)
    print(f"  [{size:>6} B]  {rel}")


def main() -> None:
    print(f"Generating fixture files in: {MEDIA_DIR}\n")

    print("Media files:")
    for rel_path, languages in _MEDIA_SPECS:
        _make_mkv(MEDIA_DIR / rel_path, languages)

    print("\nNon-media stubs:")
    for rel_path, content in _NON_MEDIA_SPECS:
        _make_stub(MEDIA_DIR / rel_path, content)

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"\nError: ffmpeg failed — {exc}", file=sys.stderr)
        print("Make sure ffmpeg is installed and available on PATH.", file=sys.stderr)
        sys.exit(1)
