from typing import Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from bot.database.models import User, PenaltyLog
from bot.database.connection import AsyncSessionLocal


class RankService:
    DEFAULT_BASE_SCORE = 100
    POINTS_PER_SUCCESSFUL_TEVKIL = 5
    POINTS_PER_TIMEOUT_PENALTY = 20

    # Kademeli Handikap Gecikme Tablosu (milisaniye cinsinden sanal sıra kaydırma)
    # Seviye 1 (1 sıra geriden): +3.000 ms
    # Seviye 2 (2 sıra geriden): +7.000 ms
    # Seviye 3 (3 sıra geriden): +15.000 ms
    # Seviye 4 (4+ sıra geriden): +30.000 ms
    HANDICAP_DELAYS_MS = {
        0: 0.0,
        1: 3000.0,
        2: 7000.0,
        3: 15000.0,
        4: 30000.0,
    }

    @staticmethod
    def calculate_net_score(rank_score: int, penalty_points: int) -> int:
        """Kullanıcının net rank puanını döner (minimum 0)."""
        return max(0, rank_score - penalty_points)

    @staticmethod
    async def get_system_average_score(db: Optional[AsyncSession] = None) -> float:
        """
        Sistemdeki tüm kayıtlı kullanıcıların net puan ortalamasını döner.
        Kullanıcı yoksa varsayılan olarak 100.0 döner.
        """
        if db is None:
            async with AsyncSessionLocal() as session:
                return await RankService._compute_average(session)
        return await RankService._compute_average(db)

    @staticmethod
    async def _compute_average(db: AsyncSession) -> float:
        stmt = select(func.avg(User.rank_score - User.penalty_points))
        res = await db.execute(stmt)
        avg = res.scalar()
        if avg is None:
            return float(RankService.DEFAULT_BASE_SCORE)
        return max(50.0, float(avg))

    @staticmethod
    def determine_handicap_level(net_score: int, average_score: float, penalty_points: int = 0) -> int:
        """
        Kullanıcının puanının ortalamaya göre düşüklüğüne ve ceza puanına göre
        1-4 arası handikap seviyesini belirler.
        0: Handikap yok (ortalama üstü veya cezasız)
        1: 1 sıra geriye atma eğilimi
        2: 2 sıra geriye atma eğilimi
        3: 3 sıra geriye atma eğilimi
        4: 4+ sıra geriye atma eğilimi
        """
        score_diff = average_score - net_score

        # Eğer kullanıcının ceza puanı yüksekse veya puanı ortalamanın çok altındaysa
        if score_diff >= 50 or penalty_points >= 35 or net_score <= 40:
            return 4
        elif score_diff >= 30 or penalty_points >= 20 or net_score <= 60:
            return 3
        elif score_diff >= 15 or penalty_points >= 10 or net_score <= 80:
            return 2
        elif score_diff > 0 or penalty_points > 0:
            return 1
        return 0

    @classmethod
    def get_handicap_delay_ms(cls, handicap_level: int) -> float:
        """Handikap seviyesine göre milisaniye gecikme miktarını döner."""
        return cls.HANDICAP_DELAYS_MS.get(handicap_level, 0.0)

    @classmethod
    async def calculate_application_score(
        cls,
        base_ms: float,
        user: User,
        db: Optional[AsyncSession] = None
    ) -> Tuple[float, int, int]:
        """
        Başvuru sırasında kullanıcı için efektif milisaniye skorunu, net puanı ve handikap seviyesini hesaplar.
        Dönüş: (effective_score_ms, net_score, handicap_level)
        """
        net_score = cls.calculate_net_score(user.rank_score, user.penalty_points)
        avg_score = await cls.get_system_average_score(db)
        handicap_lvl = cls.determine_handicap_level(net_score, avg_score, user.penalty_points)
        delay_ms = cls.get_handicap_delay_ms(handicap_lvl)

        effective_score_ms = base_ms + delay_ms
        return effective_score_ms, net_score, handicap_lvl

    @staticmethod
    async def award_successful_tevkil(creator_id: int, applicant_id: int, db: AsyncSession):
        """
        Başarıyla sonuçlanan bir tevkil için hem ilan sahibine hem de adaya +5 rank puanı verir.
        """
        # İlan sahibi
        c_stmt = select(User).where(User.id == creator_id)
        c_res = await db.execute(c_stmt)
        creator = c_res.scalar_one_or_none()
        if creator:
            creator.rank_score += RankService.POINTS_PER_SUCCESSFUL_TEVKIL
            creator.completed_tevkils_count += 1

        # Aday
        a_stmt = select(User).where(User.id == applicant_id)
        a_res = await db.execute(a_stmt)
        applicant = a_res.scalar_one_or_none()
        if applicant:
            applicant.rank_score += RankService.POINTS_PER_SUCCESSFUL_TEVKIL
            applicant.completed_tevkils_count += 1

        await db.commit()

    @staticmethod
    async def apply_penalty(
        user_id: int,
        points: int,
        reason: str,
        issued_by: str,
        db: AsyncSession
    ) -> Optional[User]:
        """
        Kullanıcıya ceza puanı ekler ve log kaydı oluşturur.
        """
        u_stmt = select(User).where(User.id == user_id)
        res = await db.execute(u_stmt)
        user = res.scalar_one_or_none()

        if not user:
            user = User(id=user_id, rank_score=100, penalty_points=points)
            db.add(user)
        else:
            user.penalty_points += points

        log_entry = PenaltyLog(
            user_id=user_id,
            points=points,
            reason=reason,
            issued_by=issued_by
        )
        db.add(log_entry)
        await db.commit()
        await db.refresh(user)
        return user
