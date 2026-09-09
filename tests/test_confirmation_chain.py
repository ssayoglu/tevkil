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


@pytest.mark.asyncio
async def test_advance_to_next_candidate_with_backup():
    from unittest.mock import AsyncMock, MagicMock, patch
    from bot.handlers.confirmation import advance_to_next_candidate_or_close
    from bot.database.models import Listing, User

    mock_bot = AsyncMock()
    mock_db = AsyncMock()

    mock_listing = Listing(
        id=55,
        creator_id=1001,
        group_id=-100555,
        status="MATCHED"
    )

    with patch("bot.handlers.confirmation.get_next_backup_candidate", new_callable=AsyncMock) as mock_get_next:
        # 2nd candidate found
        mock_get_next.return_value = (2002, 1234567.0, 2)

        # Mock DB user
        cand_user = User(id=2002, full_name="Av. Ikinci Aday", username="ikinciaday")
        res_cand = MagicMock()
        res_cand.scalar_one_or_none.return_value = cand_user
        mock_db.execute.return_value = res_cand

        with patch("bot.handlers.confirmation.update_group_listing_board", new_callable=AsyncMock) as mock_update_board:
            await advance_to_next_candidate_or_close(
                bot=mock_bot,
                listing=mock_listing,
                current_candidate_rank=1,
                db=mock_db
            )

            # Verification
            assert mock_listing.status == "MATCHED"  # Must NOT be CLOSED_DISAGREED
            assert mock_bot.send_message.called
            # Sent to creator (1001), applicant (2002), group (-100555)
            sent_chats = [call[1]["chat_id"] for call in mock_bot.send_message.call_args_list]
            assert 1001 in sent_chats
            assert 2002 in sent_chats
            assert -100555 in sent_chats
            assert mock_update_board.called
