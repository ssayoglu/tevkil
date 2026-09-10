from typing import Optional
from datetime import datetime
from aiogram import Bot
from aiogram.types import Message
from bot.config import settings
from bot.database.models import MessageLog
from bot.database.connection import AsyncSessionLocal
from bot.services.redis_queue import RedisQueueService


class AuditService:
    @staticmethod
    async def log_and_forward_to_admin(
        bot: Bot,
        listing_id: int,
        session_id: int,
        sender_id: int,
        sender_name: str,
        sender_username: Optional[str],
        sender_role: str,  # "İlan Sahibi" veya "Başvuran Aday"
        target_role: str,
        message: Message
    ):
        """
        Görüşmedeki mesajı (metin, fotoğraf, doküman/PDF) veritabanına eksiksiz loglar.
        Admin grubunda kargaşa oluşmaması için her mesajı ana kanala fırlatmak yerine
        Postgres MessageLog tablosuna kaydeder. Adminler diledikleri an '#ID log' veya
        butonla tüm mesaj geçmişini anında görebilirler.
        """
        content_type = "text"
        text_content = message.text or message.caption or ""
        file_id = None
        file_name = None

        if message.photo:
            content_type = "photo"
            file_id = message.photo[-1].file_id
        elif message.document:
            content_type = "document"
            file_id = message.document.file_id
            file_name = message.document.file_name
        elif message.voice:
            content_type = "voice"
            file_id = message.voice.file_id

        # Veritabanına kaydet
        try:
            async with AsyncSessionLocal() as db:
                db_log = MessageLog(
                    listing_id=listing_id,
                    session_id=session_id,
                    sender_id=sender_id,
                    sender_role=sender_role,
                    content_type=content_type,
                    text_content=text_content,
                    file_id=file_id,
                    file_name=file_name,
                    sent_at=datetime.utcnow()
                )
                db.add(db_log)
                await db.commit()
        except Exception as db_err:
            print(f"[AuditService] DB log kaydetme hatası: {db_err}")

    @staticmethod
    async def notify_admin_event(
        bot: Bot,
        text: str,
        reply_markup=None,
        listing_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Önemli sistem olaylarını (Yeni ilan, köprü, anlaşma, anlaşmazlık, kısıtlama, zaman aşımı)
        admin grubuna bildirir. Eğer listing_id varsa mesajları o ilanın ana bildirimine
        Yanıt (Thread/Reply) olarak gruplar; kargaşayı önler.
        """
        reply_to_id = None
        if listing_id:
            reply_to_id = await RedisQueueService.get_admin_listing_message_id(listing_id)

        try:
            msg = await bot.send_message(
                chat_id=settings.admin_chat_id,
                text=text,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_id,
                parse_mode="HTML"
            )
            if listing_id and not reply_to_id and msg:
                await RedisQueueService.set_admin_listing_message_id(listing_id, msg.message_id)
            return msg.message_id if msg else None
        except Exception:
            try:
                msg = await bot.send_message(
                    chat_id=settings.admin_chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
                if listing_id and not reply_to_id and msg:
                    await RedisQueueService.set_admin_listing_message_id(listing_id, msg.message_id)
                return msg.message_id if msg else None
            except Exception as e2:
                print(f"[AuditService] Admin event bildirim hatası: {e2}")
                return None

    @staticmethod
    async def cleanup_old_logs(days: int = 90) -> int:
        """
        3 aydan (varsayılan 90 gün) eski denetim mesaj loglarını temizler.
        Dönüş: Silinen log sayısı
        """
        from datetime import timedelta
        from sqlalchemy import delete

        cutoff = datetime.utcnow() - timedelta(days=days)
        try:
            async with AsyncSessionLocal() as db:
                stmt = delete(MessageLog).where(MessageLog.sent_at < cutoff)
                result = await db.execute(stmt)
                await db.commit()
                deleted_count = result.rowcount or 0
                if deleted_count > 0:
                    print(f"[AuditService] {deleted_count} adet {days} günden eski denetim logu temizlendi.")
                return deleted_count
        except Exception as e:
            print(f"[AuditService] Log temizleme hatası: {e}")
            return 0
