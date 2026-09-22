"""Language-code display names (Phase 12 polish)."""

from __future__ import annotations

from app.core.languages import language_display_name


def test_common_iso_639_2_codes():
    assert language_display_name("fre") == "French"
    assert language_display_name("eng") == "English"
    assert language_display_name("ger") == "German"
    assert language_display_name("jpn") == "Japanese"
    assert language_display_name("yor") == "Yoruba"
    assert language_display_name("eng ") == "English"  # whitespace tolerated


def test_iso_639_1_short_forms():
    assert language_display_name("en") == "English"
    assert language_display_name("zh") == "Chinese"


def test_special_markers():
    assert language_display_name("und") == "Undetermined"
    assert language_display_name("mul") == "Multiple languages"


def test_unknown_codes_pass_through_uppercased():
    # Honest display for a code we do not know — never dropped, never a lie.
    assert language_display_name("qaa") == "QAA"
    assert language_display_name("xyz-FOO") == "XYZ-FOO"


def test_none_and_empty():
    assert language_display_name(None) is None
    assert language_display_name("") is None
    assert language_display_name("   ") is None
