"""Unit tests for formatting helpers."""

from __future__ import annotations

import pytest

from app.utils.format import format_bitrate, format_size, format_time


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (1024 * 1024, "1.0 MiB"),
        (int(2.5 * 1024**3), "2.5 GiB"),
        (None, "—"),
        (-5, "—"),
    ],
)
def test_format_size(value, expected):
    assert format_size(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (999, "999 bps"),
        (128_000, "128 kbps"),
        (462_000, "462 kbps"),
        (1_500_000, "1.5 Mbps"),
        (None, "—"),
        (0, "—"),
        (-1, "—"),
    ],
)
def test_format_bitrate(value, expected):
    assert format_bitrate(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "--:--"),
        (-1, "--:--"),
        (0, "0:00"),
        (59.4, "0:59"),
        (61.0, "1:01"),
        (3599.0, "59:59"),
        (3600.0, "1:00:00"),
        (3661.5, "1:01:02"),
    ],
)
def test_format_time(value, expected):
    assert format_time(value) == expected
