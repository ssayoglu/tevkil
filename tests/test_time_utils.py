import pytest
from datetime import datetime, timezone
from bot.utils.time_utils import format_timestamp_ms, format_datetime_tr, format_date_short_tr


def test_format_timestamp_ms():
    # UTC timestamp: 1717240000.123456 -> 1717240000123.456 ms
    timestamp_ms = 1717240000123.456
    formatted = format_timestamp_ms(timestamp_ms)

    parts = formatted.split(".")
    assert len(parts) == 2
    assert len(parts[1]) == 3  # exactly 3 digits for milliseconds
    # Check HH:MM:SS format
    time_parts = parts[0].split(":")
    assert len(time_parts) == 3


def test_format_datetime_tr():
    dt_utc = datetime(2026, 9, 9, 17, 30, 45, tzinfo=timezone.utc)
    # In Turkey (UTC+3), 17:30 UTC is 20:30 Istanbul
    formatted = format_datetime_tr(dt_utc)
    assert "09.09.2026 20:30:45" == formatted

    assert format_datetime_tr(None) == "-"


def test_format_date_short_tr():
    dt_utc = datetime(2026, 9, 9, 17, 30, 45, tzinfo=timezone.utc)
    formatted = format_date_short_tr(dt_utc)
    assert "09.09.2026 20:30" == formatted

    assert format_date_short_tr(None) == "-"
