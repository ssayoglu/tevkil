import asyncio
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot
from sqlalchemy import select
from bot.config import settings
from bot.database.connection import AsyncSessionLocal
from bot.database.models import Listing, BridgeSession, User, PenaltyLog
from bot.services.redis_queue import RedisQueueService
from bot.services.audit_service import AuditService
from bot.services.rank_service import RankService
from bot.utils.time_utils import format_date_short_tr


class TimeoutService:
    @staticmethod
    def start_timeout_watcher(
        bot: Bot,
        listing_id: int,
        session_id: int,
        creator_id: int,
        applicant_id: int,
        group_id: int,
        timeout_seconds: Optional[int] = None
    ):
        """
        30 dakikalık zaman aşımını arka planda asenkron takip eder.
        """
        if timeout_seconds is None:
            timeout_seconds = settings.timeout_minutes * 60
            
        asyncio.create_task(
            TimeoutService._watch_timeout_task(
                bot, listing_id, session_id, creator_id, applicant_id, group_id, timeout_seconds
            )
        )

    @staticmethod
    async def _watch_timeout_task(
        bot: Bot,
        listing_id: int,
        session_id: int,
        creator_id: int,
        applicant_id: int,
        group_id: int,
        timeout_seconds: int
    ):
        await asyncio.sleep(timeout_seconds)
        await TimeoutService.handle_session_timeout(bot, session_id)

    @staticmethod
    async def handle_session_timeout(bot: Bot, session_id: int):
        """
        Süresi dolan bir oturumu iptal eder, 5 gün ban ve 20 ceza puanı uygular, bildirimleri yapar.
        """
        async with AsyncSessionLocal() as db:
            session_stmt = select(BridgeSession).where(BridgeSession.id == session_id)
            res = await db.execute(session_stmt)
            session = res.scalar_one_or_none()

            if not session or not session.is_active:
                return  # Zaten görüşme tamamlanmış veya kapatılmış

            # İlan sahibi ilk mesajı attı mı?
            if session.creator_first_message_sent:
                return  # Kural yerine getirilmiş

            listing_id = session.listing_id
            creator_id = session.creator_id
            applicant_id = session.applicant_id

            # Kural ihlali! 30 dakika doldu ve mesaj atılmadı
            now = datetime.utcnow()
            session.is_active = False
            session.closed_at = now
            session.close_reason = "TIMEOUT_NO_FIRST_MESSAGE"

            # İlan durumunu güncelle
            listing_stmt = select(Listing).where(Listing.id == listing_id)
            l_res = await db.execute(listing_stmt)
            listing = l_res.scalar_one_or_none()
            group_id = listing.group_id if listing else 0
            if listing:
                listing.status = "CANCELLED_TIMEOUT"
                listing.cancellation_reason = "İlan sahibi 30 dk içinde ilk mesajı atmadı"

            # İlan sahibini 5 gün kara listeye al ve 20 ceza puanı uygula
            ban_until = now + timedelta(days=settings.ban_duration_days)
            user_stmt = select(User).where(User.id == creator_id)
            u_res = await db.execute(user_stmt)
            user = u_res.scalar_one_or_none()
            if user:
                user.is_banned = True
                user.banned_until = ban_until
                user.ban_reason = f"30 dakika kuralı ihlali ({settings.ban_duration_days} gün kısıtlama)"
                user.penalty_points += RankService.POINTS_PER_TIMEOUT_PENALTY
                user.cancelled_tevkils_count += 1

                penalty_log = PenaltyLog(
                    user_id=creator_id,
                    points=RankService.POINTS_PER_TIMEOUT_PENALTY,
                    reason="30 dakika içinde ilk mesaj iletilmedi (otomatik ceza)",
                    issued_by="SYSTEM_TIMEOUT"
                )
                db.add(penalty_log)

            await db.commit()

        # Redis köprülerini temizle
        await RedisQueueService.remove_active_bridge(creator_id)
        await RedisQueueService.remove_active_bridge(applicant_id)

        # 1. İlan sahibine bildirim
        try:
            await bot.send_message(
                chat_id=creator_id,
                text=(
                    f"⚠️ <b>İlan İptal Edildi ve Kısıtlandınız</b>\n\n"
                    f"#{listing_id} numaralı tevkil ilanınız için eşleşme sağlandıktan sonra "
                    f"30 dakika içinde adaya ilk mesajı göndermediğiniz tespit edilmiştir.\n\n"
                    f"📌 <b>Cezai Müeyyideler:</b>\n"
                    f"• Hesabınız <b>{settings.ban_duration_days} gün</b> boyunca kısıtlanmıştır.\n"
                    f"• Hesabınıza <b>+{RankService.POINTS_PER_TIMEOUT_PENALTY} Ceza Puanı</b> işlenmiştir.\n"
                    f"• Kısıtlama Bitiş: {format_date_short_tr(ban_until)}"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[TimeoutService] İlan sahibine bildirim hatası: {e}")

        # 2. Adaya bildirim
        try:
            await bot.send_message(
                chat_id=applicant_id,
                text=(
                    f"ℹ️ <b>Tevkil Süreci Sonlandırıldı</b>\n\n"
                    f"#{listing_id} numaralı ilanın sahibi 30 dakika içerisinde görevin detaylarını "
                    f"iletmediği için ilan sistem tarafından otomatik olarak iptal edilmiştir."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[TimeoutService] Adaya bildirim hatası: {e}")

        # 3. Ana grupta duyuru
        if group_id:
            try:
                await bot.send_message(
                    chat_id=group_id,
                    text=(
                        f"📢 <b>SİSTEM DUYURUSU: İlan İptali</b>\n\n"
                        f"#{listing_id} numaralı tevkil ilanı, ilan sahibinin 30 dakika kuralına "
                        f"uymaması (ilk mesajı iletmemesi) nedeniyle sistem tarafından iptal edilmiş, "
                        f"ilgiliye <b>+{RankService.POINTS_PER_TIMEOUT_PENALTY} ceza puanı</b> ve "
                        f"<b>{settings.ban_duration_days} gün</b> kısıtlama uygulanmıştır."
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"[TimeoutService] Gruba iptal duyurusu hatası: {e}")

        # 4. Admin Denetim Grubuna Rapor
        admin_alert = (
            f"🚨 <b>[ZAMAN AŞIMI & OTOMATİK CEZA]</b>\n"
            f"📋 <b>İlan ID:</b> #{listing_id}\n"
            f"👤 <b>İlan Sahibi ID:</b> <code>{creator_id}</code>\n"
            f"⏳ <b>Durum:</b> 30 dakika doldu, ilk mesaj gönderilmedi.\n"
            f"🔒 <b>Uygulanan Ceza:</b> {settings.ban_duration_days} gün kısıtlama & +{RankService.POINTS_PER_TIMEOUT_PENALTY} Ceza Puanı.\n"
            f"📅 <b>Kısıtlama Bitiş:</b> {format_date_short_tr(ban_until)}"
        )
        await AuditService.notify_admin_event(bot, admin_alert)

    @staticmethod
    async def run_periodic_timeout_checker(bot: Bot, interval_seconds: int = 60):
        """
        Arka planda her 60 saniyede bir çalışarak veritabanındaki süresi dolmuş
        aktif oturumları kontrol eder ve iptal eder (bot restart koruması).
        """
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                async with AsyncSessionLocal() as db:
                    now = datetime.utcnow()
                    stmt = (
                        select(BridgeSession)
                        .where(
                            BridgeSession.is_active == True,
                            BridgeSession.creator_first_message_sent == False,
                            BridgeSession.timeout_at <= now
                        )
                    )
                    res = await db.execute(stmt)
                    expired_sessions = res.scalars().all()
                    session_ids = [s.id for s in expired_sessions]

                for sid in session_ids:
                    await TimeoutService.handle_session_timeout(bot, sid)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TimeoutService] Periyodik zaman aşımı kontrol hatası: {e}")
