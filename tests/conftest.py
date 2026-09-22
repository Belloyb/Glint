"""Shared fixtures: synthetic media files (no binary assets needed in git)."""

from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

import pytest

# Isolate every test run from the developer's real user configuration
# (settings, recents, logs, shortcut overrides). Must run before any
# Application object is constructed; GLINT_CONFIG_DIR is honoured by
# app.utils.paths.config_dir().
_TEST_CONFIG_DIR = Path(tempfile.mkdtemp(prefix="glint-test-config-"))
os.environ["GLINT_CONFIG_DIR"] = str(_TEST_CONFIG_DIR)

_SAMPLE_RATE = 8000


def make_wav(path: Path, seconds: float = 3.0, frequency: int = 440) -> Path:
    """Write a small mono sine-wave WAV using only the standard library."""
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SAMPLE_RATE)
        frames = bytearray()
        for i in range(int(_SAMPLE_RATE * seconds)):
            frames += struct.pack("<h", int(11000 * math.sin(2 * math.pi * frequency * i / _SAMPLE_RATE)))
        handle.writeframes(bytes(frames))
    return path


@pytest.fixture(scope="session")
def sample_wav(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_wav(tmp_path_factory.mktemp("media") / "tone.wav")


@pytest.fixture(scope="session")
def corrupt_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("media") / "garbage.mkv"
    path.write_bytes(b"\x00" * 64 + b"definitely not a matroska file" + b"\xff" * 64)
    return path


SRT_MAIN = "1\n00:00:00,500 --> 00:00:02,000\nHello subtitles\n\n2\n00:00:02,100 --> 00:00:03,900\nSecond line\n"
SRT_EN = "1\n00:00:01,000 --> 00:00:02,500\nEnglish external track\n"


@pytest.fixture(scope="session")
def subtitle_media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """movie.mkv (embedded SRT) + movie.srt + movie.en.srt in one directory.

    The external files share the video stem so the engine's fuzzy
    auto-load picks them up when movie.mkv is opened.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available to generate subtitle test media")
    directory = tmp_path_factory.mktemp("subs")
    base = directory / "movie"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest",
            str(base) + "_video.mp4",
        ],
        check=True,
        timeout=60,
    )
    (directory / "movie.srt").write_text(SRT_MAIN, encoding="utf-8")
    (directory / "movie.en.srt").write_text(SRT_EN, encoding="utf-8")
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(base) + "_video.mp4",
            "-i", str(directory / "movie.srt"),
            "-c", "copy", "-c:s", "srt",
            str(base) + ".mkv",
        ],
        check=True,
        timeout=60,
    )
    (directory / "movie_video.mp4").unlink()  # intermediate, not part of the fixture
    return directory


@pytest.fixture(scope="session")
def subtitle_mkv(subtitle_media_dir: Path) -> Path:
    return subtitle_media_dir / "movie.mkv"


@pytest.fixture(scope="session")
def external_srt(subtitle_media_dir: Path) -> Path:
    return subtitle_media_dir / "movie.srt"


@pytest.fixture(scope="session")
def sample_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small real video (MPEG-4 + AAC). Skips when ffmpeg is unavailable."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available to generate a test video")
    path = tmp_path_factory.mktemp("media") / "clip.mp4"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        timeout=60,
    )
    return path


_SRT_MAIN_SUBS = "1\n00:00:00,500 --> 00:00:02,000\nMain subs\n"


@pytest.fixture(scope="session")
def multi_track_mkv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """multi.mkv: two titled video tracks, two audio tracks (eng/fre), one
    embedded SRT — for Phase 8 track-selection tests."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not available to generate multi-track test media")
    directory = tmp_path_factory.mktemp("multitrack")
    srt = directory / "sub.srt"
    srt.write_text(_SRT_MAIN_SUBS, encoding="utf-8")
    path = directory / "multi.mkv"
    subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=4",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=12:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=4",
            "-i", str(srt),
            "-map", "0:v", "-map", "1:v", "-map", "2:a", "-map", "3:a", "-map", "4:s",
            "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-b:a", "32k", "-c:s", "srt",
            "-metadata:s:v:0", "title=Main video",
            "-metadata:s:v:1", "title=Bonus video",
            "-metadata:s:a:0", "language=eng",
            "-metadata:s:a:1", "language=fre",
            str(path),
        ],
        check=True,
        timeout=60,
    )
    return path
