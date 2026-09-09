import pytest
from datetime import datetime


def test_millisecond_timestamp_formatting():
    # 1717240000.123456 -> 1717240000123.456 ms
    timestamp_ms = 1717240000123.456
    dt = datetime.fromtimestamp(timestamp_ms / 1000.0)
    formatted = dt.strftime("%H:%M:%S.%f")[:-3]
    
    # Format must be HH:MM:SS.mmm (length 12: 2 + 1 + 2 + 1 + 2 + 1 + 3)
    parts = formatted.split(".")
    assert len(parts) == 2
    assert len(parts[1]) == 3  # exactly 3 digits for milliseconds


def test_disagreement_routing():
    # Şartname kuralı: "Sebep 'Ücret' harici seçildiğinde otomatik olarak sıradaki 2. kişiye mesaj gönderir"
    reasons = ["ucret", "mesafe", "kidem", "diger"]
    should_route_to_next = {r: (r != "ucret") for r in reasons}
    
    assert should_route_to_next["ucret"] is False
    assert should_route_to_next["mesafe"] is True
    assert should_route_to_next["kidem"] is True
    assert should_route_to_next["diger"] is True
