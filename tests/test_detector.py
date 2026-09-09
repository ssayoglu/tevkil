import pytest
from bot.handlers.group_detector import is_tevkil_message


def test_tevkil_detection_positive():
    assert is_tevkil_message("İstanbul Çağlayan Adliyesi için tevkildir.")
    assert is_tevkil_message("Acil TEVKİLDİR arkadaşlar")
    assert is_tevkil_message("Tevkildir: Yarın saat 10:00 Kartal 2. Asliye Ceza")
    assert is_tevkil_message("Bu iş bir tevkildir, detaylar özelden")


def test_tevkil_detection_negative():
    assert not is_tevkil_message("Tevkil arayan var mı?")
    assert not is_tevkil_message("Merhaba iyi çalışmalar dilerim")
    assert not is_tevkil_message("")
    assert not is_tevkil_message(None)
    assert not is_tevkil_message("tevkildirr")  # Kelime sınırı kontrolü
