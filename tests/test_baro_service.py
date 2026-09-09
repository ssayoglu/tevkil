import pytest
from bot.services.baro_service import BaroVerificationService


def test_baro_sicil_format():
    # Valid sicil numbers
    assert BaroVerificationService.validate_sicil_format("12345") is True
    assert BaroVerificationService.validate_sicil_format("123") is True
    assert BaroVerificationService.validate_sicil_format("1234567") is True
    assert BaroVerificationService.validate_sicil_format("  45678  ") is True

    # Invalid sicil numbers
    assert BaroVerificationService.validate_sicil_format("") is False
    assert BaroVerificationService.validate_sicil_format(None) is False
    assert BaroVerificationService.validate_sicil_format("12") is False  # Too short (< 3)
    assert BaroVerificationService.validate_sicil_format("12345678") is False  # Too long (> 7)
    assert BaroVerificationService.validate_sicil_format("1234a") is False  # Contains non-digits
    assert BaroVerificationService.validate_sicil_format("abcde") is False


def test_normalize_baro_name():
    assert BaroVerificationService.normalize_baro_name("istanbul") == "İstanbul"
    assert BaroVerificationService.normalize_baro_name("ist") == "İstanbul"
    assert BaroVerificationService.normalize_baro_name("ankara 2") == "Ankara 2 No'lu"
    assert BaroVerificationService.normalize_baro_name("izmir barosu") == "İzmir"
    assert BaroVerificationService.normalize_baro_name("antalya") == "Antalya"


def test_baro_selection_keyboard():
    kb = BaroVerificationService.get_baro_selection_keyboard()
    assert kb is not None
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "baro_sel:İstanbul" in callbacks
    assert "baro_sel:Ankara" in callbacks
    assert "baro_sel:İzmir" in callbacks
    assert "baro_sel:OTHER" in callbacks
    assert "baro_sel:CANCEL" in callbacks


@pytest.mark.asyncio
async def test_approve_verification():
    from unittest.mock import AsyncMock, MagicMock
    from bot.database.models import User

    mock_bot = AsyncMock()
    mock_db = AsyncMock()

    user = User(
        id=5001,
        full_name="Av. Mehmet",
        baro_name="İstanbul",
        baro_sicil_no="55443",
        rank_score=100,
        is_baro_verified=False
    )
    res = MagicMock()
    res.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = res

    result = await BaroVerificationService.approve_verification(
        bot=mock_bot,
        user_id=5001,
        admin_name="Admin Serkan",
        db=mock_db
    )

    assert result["success"] is True
    assert user.is_baro_verified is True
    assert user.baro_verification_status == "VERIFIED"
    assert user.rank_score == 110  # +10 points bonus
    assert mock_bot.send_message.called


@pytest.mark.asyncio
async def test_reject_verification():
    from unittest.mock import AsyncMock, MagicMock
    from bot.database.models import User

    mock_bot = AsyncMock()
    mock_db = AsyncMock()

    user = User(
        id=5002,
        full_name="Av. Ali",
        baro_name="Ankara",
        baro_sicil_no="12345",
        rank_score=100,
        is_baro_verified=True
    )
    res = MagicMock()
    res.scalar_one_or_none.return_value = user
    mock_db.execute.return_value = res

    result = await BaroVerificationService.reject_verification(
        bot=mock_bot,
        user_id=5002,
        reason_code="belge",
        admin_name="Admin Serkan",
        db=mock_db
    )

    assert result["success"] is True
    assert user.is_baro_verified is False
    assert user.baro_verification_status == "REJECTED"
    assert mock_bot.send_message.called

