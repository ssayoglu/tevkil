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
