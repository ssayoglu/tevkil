import pytest
from bot.handlers.confirmation import get_next_candidate_keyboard, get_reason_keyboard


def test_next_candidate_keyboard_generation():
    kb = get_next_candidate_keyboard(listing_id=101, current_rank=2)
    buttons = kb.inline_keyboard[0]
    assert len(buttons) == 2
    assert buttons[0].callback_data == "next_offer:accept:101:2"
    assert buttons[1].callback_data == "next_offer:decline:101:2"


def test_reason_keyboard_generation():
    kb = get_reason_keyboard(listing_id=101, role_prefix="creator")
    all_callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "reason:creator:101:tarife_alti" in all_callbacks
    assert "reason:creator:101:ucret" in all_callbacks
    assert "reason:creator:101:mesafe" in all_callbacks
    assert "reason:creator:101:kidem" in all_callbacks
    assert "reason:creator:101:diger" in all_callbacks
