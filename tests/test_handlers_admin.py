import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import User as TelegramUser, Message, Chat
from bot.handlers.admin_panel import is_admin_chat, cmd_admin_help
from bot.config import settings


def test_is_admin_chat():
    settings.admin_chat_id = -1001234567890
    msg_admin = MagicMock(spec=Message)
    msg_admin.chat = Chat(id=-1001234567890, type="supergroup")

    msg_non_admin = MagicMock(spec=Message)
    msg_non_admin.chat = Chat(id=-1009999999999, type="supergroup")

    assert is_admin_chat(msg_admin) is True
    assert is_admin_chat(msg_non_admin) is False


@pytest.mark.asyncio
async def test_cmd_admin_help():
    settings.admin_chat_id = -1001234567890
    message = MagicMock(spec=Message)
    message.chat = Chat(id=-1001234567890, type="supergroup")
    message.reply = AsyncMock()

    await cmd_admin_help(message)
    assert message.reply.called
    reply_text = message.reply.call_args[0][0]
    assert "/durdur" in reply_text
    assert "/tarife_ban" in reply_text
    assert "/kullanici_kisitla" in reply_text
    assert "/ceza_puani_ver" in reply_text
    assert "/istatistik" in reply_text
    assert "/tum_kisitlari_kaldir" in reply_text

    # Verify inline keyboard is attached
    reply_markup = message.reply.call_args[1].get("reply_markup")
    assert reply_markup is not None
    assert any("Tüm Kısıtları Kaldır" in btn.text for row in reply_markup.inline_keyboard for btn in row)
