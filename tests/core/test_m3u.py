"""Unit tests for M3U/M3U8 parsing and writing."""

from __future__ import annotations

from pathlib import Path

from app.core import m3u


def test_roundtrip(tmp_path: Path):
    path = tmp_path / "list.m3u8"
    entries = [
        m3u.M3uEntry(uri="/a/song.mp3", title="Song", duration=123.0),
        m3u.M3uEntry(uri="https://example.com/stream"),
    ]
    m3u.save(path, entries)
    assert m3u.load(path) == entries


def test_parse_extinf_and_paths():
    text = "#EXTM3U\n#EXTINF:123,My Song\n/songs/my song.mp3\n#EXTINF:-1,Broken\nbad.mkv\n"
    entries = m3u.parse(text)
    assert entries[0].uri == "/songs/my song.mp3"
    assert entries[0].title == "My Song"
    assert entries[0].duration == 123.0
    assert entries[1].title == "Broken"
    assert entries[1].duration is None  # -1 means unknown


def test_relative_paths_resolve_against_base_dir(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    playlist = tmp_path / "sub" / "list.m3u8"
    playlist.write_text("track.mp3\n../other/flac file.flac\n", encoding="utf-8")
    entries = m3u.load(playlist)
    assert entries[0].uri == str(tmp_path / "sub" / "track.mp3")
    assert entries[1].uri == str(tmp_path / "other" / "flac file.flac")


def test_urls_kept_verbatim():
    entries = m3u.parse("http://a/b.mp4\nrtsp://cam/stream\nfile:///x/y.mp3\n")
    assert [entry.uri for entry in entries] == [
        "http://a/b.mp4",
        "rtsp://cam/stream",
        "file:///x/y.mp3",
    ]


def test_crlf_blank_lines_comments_and_unknown_directives():
    text = (
        "#EXTM3U\r\n"
        "\r\n"
        "#EXTVLCOPT:some=option\r\n"
        "  # a comment\r\n"
        "a.mp3\r\n"
        "\r\n"
        "b.mp3\n"
    )
    entries = m3u.parse(text)
    assert [entry.uri for entry in entries] == ["a.mp3", "b.mp3"]


def test_utf8_bom_and_latin1_fallback(tmp_path: Path):
    bom = tmp_path / "bom.m3u8"
    bom.write_bytes("﻿café.mp3\n".encode())
    assert m3u.load(bom)[0].uri.endswith("café.mp3")

    latin = tmp_path / "latin.m3u"
    latin.write_bytes("café.mp3\n".encode("latin-1"))
    assert m3u.load(latin)[0].uri.endswith("café.mp3")


def test_extinf_without_duration():
    entries = m3u.parse("#EXTM3U\n#EXTINF:,Title Only\nx.mp3\n")
    assert entries[0].title == "Title Only"
    assert entries[0].duration is None


def test_empty_file_gives_no_entries(tmp_path: Path):
    path = tmp_path / "empty.m3u8"
    path.write_text("", encoding="utf-8")
    assert m3u.load(path) == []
    assert m3u.parse("#EXTM3U\n# nothing else\n") == []


def test_missing_extm3u_header_still_parses():
    entries = m3u.parse("a.mp3\n")
    assert len(entries) == 1


def test_gigantic_lines_are_skipped():
    hostile = "x" * 5000 + "\nok.mp3\n"
    entries = m3u.parse(hostile)
    assert [entry.uri for entry in entries] == ["ok.mp3"]


def test_trailing_extinf_without_track_is_dropped():
    entries = m3u.parse("#EXTM3U\n#EXTINF:10,Orphan\n")
    assert entries == []
