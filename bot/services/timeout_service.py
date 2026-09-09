import asyncio
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot
from sqlalchemy import select
from bot.config import settings
from bot.database.connection import AsyncSessionLocal
from bot.database.models import Listing, BridgeSession, User
from bot.services.redis_queue import RedisQueueService
from bot.services.audit_service import AuditService


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

        async with AsyncSessionLocal() as db:
            session_stmt = select(BridgeSession).where(BridgeSession.id == session_id)
            res = await db.execute(session_stmt)
            session = res.scalar_one_or_none()

            if not session or not session.is_active:
                return  # Zaten görüşme tamamlanmış veya kapatılmış

            # İlan sahibi ilk mesajı attı mı?
            if session.creator_first_message_sent:
                return  # Kural yerine getirilmiş

            # Kural ihlali! 30 dakika doldu ve mesaj atılmadı
            now = datetime.utcnow()
            session.is_active = False
            session.closed_at = now
            session.close_reason = "TIMEOUT_NO_FIRST_MESSAGE"

            # İlan durumunu güncelle
            listing_stmt = select(Listing).where(Listing.id == listing_id)
            l_res = await db.execute(listing_stmt)
            listing = l_res.scalar_one_or_none()
            if listing:
                listing.status = "CANCELLED_TIMEOUT"
                listing.cancellation_reason = "İlan sahibi 30 dk içinde ilk mesajı atmadı"

            # İlan sahibini 5 gün kara listeye al
            ban_until = now + timedelta(days=settings.ban_duration_days)
            user_stmt = select(User).where(User.id == creator_id)
            u_res = await db.execute(user_stmt)
            user = u_res.scalar_one_or_none()
            if user:
                user.is_banned = True
                user.banned_until = ban_until
                user.ban_reason = f"30 dakika kuralı ihlali ({settings.ban_duration_days} gün kısıtlama)"

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
                    f"📌 <b>Cezai Müeyyide:</b> Sistem kuralları gereğince hesabınız "
                    f"<b>{settings.ban_duration_days} gün</b> boyunca yeni ilan vermeye ve başvurmaya kapatılmıştır."
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
        try:
            await bot.send_message(
                chat_id=group_id,
                text=(
                    f"📢 <b>SİSTEM DUYURUSU: İlan İptali</b>\n\n"
                    f"#{listing_id} numaralı tevkil ilanı, ilan sahibinin 30 dakika kuralına "
                    f"uymaması (ilk mesajı iletmemesi) nedeniyle sistem tarafından iptal edilmiş "
                    f"ve ilgilinin sisteme erişimi geçici olarak kısıtlanmıştır."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[TimeoutService] Gruba iptal duyurusu hatası: {e}")

        # 4. Admin Denetim Grubuna Rapor
        admin_alert = (
            f"🚨 <b>[ZAMAN AŞIMI & OTOMATİK KISITLAMA]</b>\n"
            f"📋 <b>İlan ID:</b> #{listing_id}\n"
            f"👤 <b>İlan Sahibi ID:</b> <code>{creator_id}</code>\n"
            f"⏳ <b>Durum:</b> 30 dakika doldu, ilk mesaj gönderilmedi.\n"
            f"🔒 <b>Uygulanan Ceza:</b> 5 gün sistemden men edildi.\n"
            f"📅 <b>Kısıtlama Bitiş:</b> {ban_until.strftime('%d.%m.%Y %H:%M')}"
        )
        await AuditService.notify_admin_event(bot, admin_alert)
