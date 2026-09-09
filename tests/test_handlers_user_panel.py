import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import User as TelegramUser, Message, Chat
from bot.handlers.user_panel import cmd_start, cmd_help, cmd_profile
from bot.database.models import User


@pytest.mark.asyncio
async def test_cmd_start(mocker):
    # Mock message with MagicMock to avoid pydantic frozen model constraints
    message = MagicMock(spec=Message)
    message.from_user = TelegramUser(id=123456, is_bot=False, first_name="Ahmet", last_name="Yılmaz", username="ahmety")
    message.chat = Chat(id=123456, type="private")
    message.text = "/start"
    message.reply = AsyncMock()

    # Mock DB session
    db = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = User(
        id=123456,
        full_name="Ahmet Yılmaz",
        username="ahmety",
        rank_score=100,
        penalty_points=0
    )
    db.execute.return_value = mock_res

    await cmd_start(message, db)
    assert message.reply.called
    reply_text = message.reply.call_args[0][0]
    assert "Ahmet Yılmaz" in reply_text
    assert "Rank Puanı" in reply_text


@pytest.mark.asyncio
async def test_cmd_help():
    message = MagicMock(spec=Message)
    message.reply = AsyncMock()

    await cmd_help(message)
    assert message.reply.called
    reply_text = message.reply.call_args[0][0]
    assert "30 Dakika Kuralı" in reply_text
    assert "Milisaniye Sıralama" in reply_text
