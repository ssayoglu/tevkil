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
            assert mock_update_board.called


def test_bridge_reply_keyboard():
    from bot.services.bridge_service import get_bridge_reply_keyboard
    kb = get_bridge_reply_keyboard()
    assert kb.resize_keyboard is True
    assert kb.persistent is True
    assert len(kb.keyboard[0]) == 2
    assert kb.keyboard[0][0].text == "🤝 Anlaştık"
    assert kb.keyboard[0][1].text == "❌ Anlaşamadık"


@pytest.mark.asyncio
async def test_execute_agree_step_both_parties():
    from unittest.mock import AsyncMock, MagicMock, patch
    from bot.handlers.confirmation import execute_agree_step
    from bot.database.models import Listing, BridgeSession

    mock_bot = AsyncMock()
    mock_db = AsyncMock()

    listing = Listing(id=77, creator_id=101, group_id=-1001, status="MATCHED")
    session = BridgeSession(
        id=1,
        listing_id=77,
        creator_id=101,
        applicant_id=202,
        is_active=True,
        creator_agreed=True,
        applicant_agreed=False
    )

    def mock_db_exec(stmt):
        m = MagicMock()
        stmt_str = str(stmt).lower()
        if "bridge_session" in stmt_str or "bridgesession" in stmt_str:
            m.scalar_one_or_none.return_value = session
        elif "listing" in stmt_str:
            m.scalar_one_or_none.return_value = listing
        else:
            m.scalar_one_or_none.return_value = None
        return m

    mock_db.execute = AsyncMock(side_effect=mock_db_exec)

    with patch("bot.services.redis_queue.RedisQueueService.remove_active_bridge", new_callable=AsyncMock), \
         patch("bot.services.rank_service.RankService.award_successful_tevkil", new_callable=AsyncMock), \
         patch("bot.services.audit_service.AuditService.notify_admin_event", new_callable=AsyncMock), \
         patch("bot.handlers.confirmation.update_group_listing_board", new_callable=AsyncMock):
        
        # Applicant executes agree step
        await execute_agree_step(
            bot=mock_bot,
            user_id=202,
            listing_id=77,
            db=mock_db
        )

        assert session.applicant_agreed is True
        assert session.is_active is False
        assert session.close_reason == "AGREED"
        assert listing.status == "COMPLETED"

