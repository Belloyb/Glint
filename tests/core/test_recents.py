"""Unit tests for the recent-files store."""

from __future__ import annotations

import json
from pathlib import Path

from app.core.recents import RecentFiles


def test_add_orders_newest_first_and_dedupes(tmp_path: Path):
    recents = RecentFiles(tmp_path / "recents.json")
    recents.add("a")
    recents.add("b")
    recents.add("a")  # moves to front, no duplicate
    assert recents.entries() == ("a", "b")


def test_limit_is_enforced(tmp_path: Path):
    recents = RecentFiles(tmp_path / "recents.json", limit=3)
    for i in range(6):
        recents.add(f"m{i}")
    assert recents.entries() == ("m5", "m4", "m3")


def test_remove_and_clear(tmp_path: Path):
    recents = RecentFiles(tmp_path / "recents.json")
    recents.add("a")
    recents.add("b")
    recents.remove("a")
    assert recents.entries() == ("b",)
    recents.clear()
    assert recents.entries() == ()


def test_persistence_roundtrip(tmp_path: Path):
    path = tmp_path / "recents.json"
    RecentFiles(path).add("kept")
    assert RecentFiles(path).entries() == ("kept",)


def test_corrupt_file_starts_empty(tmp_path: Path):
    path = tmp_path / "recents.json"
    path.write_text("{not json", encoding="utf-8")
    assert RecentFiles(path).entries() == ()


def test_non_list_root_starts_empty(tmp_path: Path):
    path = tmp_path / "recents.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert RecentFiles(path).entries() == ()


def test_entries_filtered_to_strings(tmp_path: Path):
    path = tmp_path / "recents.json"
    path.write_text(json.dumps([1, "ok", None, ""]), encoding="utf-8")
    assert RecentFiles(path).entries() == ("ok",)
