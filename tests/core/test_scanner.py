"""Unit tests for media file discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.scanner import is_media_file, scan_directory


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path


def _make_tree(root: Path) -> None:
    (root / "sub").mkdir()
    (root / "a.MP4").write_bytes(b"x")
    (root / "b.mkv").write_bytes(b"x")
    (root / "notes.txt").write_bytes(b"x")
    (root / "archive.zip").write_bytes(b"x")
    (root / "sub" / "c.mp3").write_bytes(b"x")
    (root / "sub" / "d.docx").write_bytes(b"x")


def test_is_media_file_case_insensitive():
    assert is_media_file(Path("movie.Mp4"))
    assert is_media_file(Path("song.FLAC"))
    assert not is_media_file(Path("file.txt"))
    assert not is_media_file(Path("noext"))


def test_scan_non_recursive(root: Path):
    _make_tree(root)
    result = scan_directory(root)
    assert [p.name for p in result] == ["a.MP4", "b.mkv"]


def test_scan_recursive(root: Path):
    _make_tree(root)
    result = scan_directory(root, recursive=True)
    assert [p.name for p in result] == ["a.MP4", "b.mkv", "c.mp3"]


def test_scan_missing_directory_returns_empty(tmp_path: Path):
    assert scan_directory(tmp_path / "nope") == []


def test_scan_unreadable_root_returns_empty(monkeypatch, root: Path):
    def raise_permission(self):
        raise PermissionError("denied")

    monkeypatch.setattr("os.scandir", raise_permission)
    assert scan_directory(root) == []


def test_scan_sorts_case_insensitively(root: Path):
    for name in ("zeta.mp3", "Alpha.mp3", "BETA.mp3"):
        (root / name).write_bytes(b"x")
    assert [p.name for p in scan_directory(root)] == ["Alpha.mp3", "BETA.mp3", "zeta.mp3"]
