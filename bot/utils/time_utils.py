from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

# Türkiye Saat Dilimi: Europe/Istanbul (UTC+3)
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")


def get_current_istanbul_time() -> datetime:
    """Mevcut Türkiye yerel saatini döner."""
    return datetime.now(ISTANBUL_TZ)


def format_timestamp_ms(timestamp_ms: float) -> str:
    """
    Milisaniye cinsinden zamanı Türkiye saatine göre 'HH:MM:SS.mmm' formatına çevirir.
    Örnek: 1717240000123.456 -> 14:32:15.123
    """
    dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).astimezone(ISTANBUL_TZ)
    return dt.strftime("%H:%M:%S.%f")[:-3]


def format_datetime_tr(dt: Optional[datetime]) -> str:
    """
    Datetime nesnesini 'DD.MM.YYYY HH:MM:SS' formatında Türkiye saatine çevirir.
    """
    if not dt:
        return "-"
    if dt.tzinfo is None:
        # UTC kabul edip Istanbul'a çevir
        dt = dt.replace(tzinfo=timezone.utc).astimezone(ISTANBUL_TZ)
    else:
        dt = dt.astimezone(ISTANBUL_TZ)
    return dt.strftime("%d.%m.%Y %H:%M:%S")


def format_date_short_tr(dt: Optional[datetime]) -> str:
    """
    Datetime nesnesini 'DD.MM.YYYY HH:MM' formatında Türkiye saatine çevirir.
    """
    if not dt:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(ISTANBUL_TZ)
    else:
        dt = dt.astimezone(ISTANBUL_TZ)
    return dt.strftime("%d.%m.%Y %H:%M")
