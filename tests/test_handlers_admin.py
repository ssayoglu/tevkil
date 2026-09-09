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
    reply_markup = message.reply.call_args[1].get("reply_markup")
    assert reply_markup is not None
    assert any("Tüm Kısıtları Kaldır" in btn.text for row in reply_markup.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_render_listing_logs_dossier():
    from bot.handlers.admin_panel import render_listing_logs_dossier
    from bot.database.models import Listing, User, MessageLog, BridgeSession
    from datetime import datetime

    mock_db = AsyncMock()

    # Mock listing
    mock_listing = Listing(
        id=99,
        group_id=-100123,
        group_title="Test Baro Grubu",
        creator_id=1001,
        raw_text="Test İlan Detayı",
        status="COMPLETED",
        created_at=datetime.utcnow()
    )

    # Mock creator user
    mock_creator = User(id=1001, full_name="Av. Test Sahip", username="testsahip")

    # Mock logs
    mock_log1 = MessageLog(
        id=1,
        listing_id=99,
        sender_id=1001,
        sender_role="İlan Sahibi",
        content_type="text",
        text_content="Merhaba dosya bilgileri...",
        sent_at=datetime.utcnow()
    )
    mock_log2 = MessageLog(
        id=2,
        listing_id=99,
        sender_id=2002,
        sender_role="Başvuran Aday",
        content_type="document",
        file_name="yetki.pdf",
        text_content="Yetki belgesi ektedir",
        sent_at=datetime.utcnow()
    )

    # Mock execute return values
    res_listing = MagicMock()
    res_listing.scalar_one_or_none.return_value = mock_listing

    res_creator = MagicMock()
    res_creator.scalar_one_or_none.return_value = mock_creator

    res_session = MagicMock()
    res_session.scalar_one_or_none.return_value = None

    res_logs = MagicMock()
    res_logs.scalars.return_value.all.return_value = [mock_log1, mock_log2]

    mock_db.execute.side_effect = [res_listing, res_creator, res_session, res_logs]

    dossier, kb = await render_listing_logs_dossier(99, mock_db)
    assert dossier is not None
    assert "İLAN #99 DENETİM VE MESAJ LOGLARI" in dossier
    assert "Av. Test Sahip" in dossier
    assert "yetki.pdf" in dossier
    assert "3 ay / 90 gün" in dossier
    assert kb is not None
