import pytest
from bot.handlers.group_detector import is_tevkil_message


def test_tevkil_detection_positive_tevkildir():
    assert is_tevkil_message("İstanbul Çağlayan Adliyesi için tevkildir.")
    assert is_tevkil_message("Acil TEVKİLDİR arkadaşlar")
    assert is_tevkil_message("Tevkildir: Yarın saat 10:00 Kartal 2. Asliye Ceza")
    assert is_tevkil_message("Bu iş bir tevkildir, detaylar özelden")


def test_tevkil_detection_positive_courthouses_with_context():
    # Kullanıcının verdiği örnek 1: Bursa
    assert is_tevkil_message("Bursa için yarın 4.10 duruşmasına katılacak var mı?")
    
    # Kullanıcının verdiği örnek 2: Bayramiç (Çanakkale ilçesi)
    assert is_tevkil_message("bayramiç devlet kurumuna evrak teslim edilecek, bir meslektaşımız var mı acaba?")
    
    # Diğer il / ilçe adliyeleri
    assert is_tevkil_message("mersin 5 asliye hukuk")
    assert is_tevkil_message("mersin 5. asliye hukuk tevkil")
    assert is_tevkil_message("Yarın Çağlayan 3. Asliye Hukuk duruşmasına girebilecek meslektaş aranıyor")
    assert is_tevkil_message("Bodrum adliyesinde dosya inceleyecek avukat var mı?")
    assert is_tevkil_message("Çorlu icra müdürlüğünde hacze gidebilecek meslektaşımız var mıdır?")
    assert is_tevkil_message("Kuşadası mahkemesinde yetki belgesiyle duruşmaya katılacak meslektaş aranmaktadır")


def test_tevkil_detection_negative_exceptions():
    # Kullanıcının şartı: "içerisinde tevkil değildir geçiyorsa saymayalım"
    assert not is_tevkil_message("Bu iş bir tevkil değildir, sadece bilgi amaçlı paylaşımdır.")
    assert not is_tevkil_message("Bursa duruşması hakkında bilgi, tevkil değildir.")
    assert not is_tevkil_message("Tevkil değil sadece bir soru sormak istemiştim.")
    assert not is_tevkil_message("Tevkildir değildir")


def test_tevkil_detection_negative_general():
    assert not is_tevkil_message("Merhaba herkese iyi çalışmalar dilerim.")
    assert not is_tevkil_message("")
    assert not is_tevkil_message(None)
    assert not is_tevkil_message("Bursa'da hava çok güzel.")  # Adliye var ama görev/tevkil bağlamı yok
    assert not is_tevkil_message("tevkildirr")


@pytest.mark.asyncio
async def test_send_welcome_and_onboarding():
    from unittest.mock import AsyncMock, MagicMock
    from aiogram.types import User as TelegramUser
    from bot.handlers.group_detector import send_welcome_and_onboarding

    mock_bot = AsyncMock()
    mock_bot.get_me.return_value = MagicMock(username="Tevkil_Denetim_Merkezi_bot")
    mock_db = AsyncMock()

    res = MagicMock()
    res.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = res

    new_user = TelegramUser(id=9988, is_bot=False, first_name="Mehmet", username="mehmetav")

    await send_welcome_and_onboarding(
        bot=mock_bot,
        chat_id=-10019999,
        new_user=new_user,
        db=mock_db
    )

    # Verifications
    assert mock_db.add.called
    assert mock_bot.send_message.called
    # Check that welcome message with deep link was sent to group
    sent_args = mock_bot.send_message.call_args_list[-1]
    assert sent_args[1]["chat_id"] == -10019999
    assert "start=baro_verify" in str(sent_args[1]["reply_markup"])

