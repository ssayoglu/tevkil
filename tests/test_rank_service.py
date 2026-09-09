import pytest
from bot.services.rank_service import RankService
from bot.database.models import User


def test_net_score_calculation():
    # Normal user
    assert RankService.calculate_net_score(100, 0) == 100
    # User with rewards
    assert RankService.calculate_net_score(125, 0) == 125
    # User with penalties
    assert RankService.calculate_net_score(100, 20) == 80
    # Penalty exceeds score -> min 0
    assert RankService.calculate_net_score(50, 60) == 0


def test_handicap_level_determination():
    # Average score is 100
    avg = 100.0

    # User with 110 points, no penalty -> Level 0 (no handicap)
    assert RankService.determine_handicap_level(net_score=110, average_score=avg, penalty_points=0) == 0

    # User with 100 points, no penalty -> Level 0
    assert RankService.determine_handicap_level(net_score=100, average_score=avg, penalty_points=0) == 0

    # User with 90 points (diff: 10, < 15) -> Level 1
    assert RankService.determine_handicap_level(net_score=90, average_score=avg, penalty_points=0) == 1

    # User with 80 points (diff: 20, >= 15) -> Level 2
    assert RankService.determine_handicap_level(net_score=80, average_score=avg, penalty_points=0) == 2

    # User with 65 points (diff: 35, >= 30) -> Level 3
    assert RankService.determine_handicap_level(net_score=65, average_score=avg, penalty_points=0) == 3

    # User with 40 points (diff: 60, >= 50) -> Level 4
    assert RankService.determine_handicap_level(net_score=40, average_score=avg, penalty_points=0) == 4

    # High penalty points override
    assert RankService.determine_handicap_level(net_score=95, average_score=avg, penalty_points=35) == 4


def test_handicap_delay_mapping():
    assert RankService.get_handicap_delay_ms(0) == 0.0
    assert RankService.get_handicap_delay_ms(1) == 3000.0
    assert RankService.get_handicap_delay_ms(2) == 7000.0
    assert RankService.get_handicap_delay_ms(3) == 15000.0
    assert RankService.get_handicap_delay_ms(4) == 30000.0


@pytest.mark.asyncio
async def test_application_score_calculation(mocker):
    # Mock system average to 100.0
    mocker.patch.object(RankService, "get_system_average_score", return_value=100.0)

    # 1. Clean user with 105 points
    user1 = User(id=1, rank_score=105, penalty_points=0)
    base_ms = 1717240000000.0
    score_ms1, net1, lvl1 = await RankService.calculate_application_score(base_ms, user1)
    assert net1 == 105
    assert lvl1 == 0
    assert score_ms1 == base_ms  # No delay

    # 2. Penalized user with 20 penalty points (net = 80, handicap level = 2, delay = 7000 ms)
    user2 = User(id=2, rank_score=100, penalty_points=20)
    score_ms2, net2, lvl2 = await RankService.calculate_application_score(base_ms, user2)
    assert net2 == 80
    assert lvl2 in [2, 3]
    assert score_ms2 > base_ms  # Delayed by handicap
