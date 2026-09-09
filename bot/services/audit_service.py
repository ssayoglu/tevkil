from typing import Optional
from aiogram import Bot
from aiogram.types import Message
from bot.config import settings
from bot.database.models import MessageLog
from bot.database.connection import AsyncSessionLocal
from datetime import datetime


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
        Görüşmedeki mesajı (metin, fotoğraf, doküman/PDF) veritabanına loglar
        ve anlık olarak Admin Denetim Grubu'na iletir.
        """
        uname_str = f"(@{sender_username})" if sender_username else ""
        header = (
            f"🛡️ <b>[DENETİM LOGU — İlan #{listing_id}]</b>\n"
            f"👤 <b>Gönderen:</b> {sender_role} - {sender_name} {uname_str} (ID: <code>{sender_id}</code>)\n"
            f"🎯 <b>Hedef:</b> {target_role}\n"
            f"⏰ <b>Zaman:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
            f"────────────────────\n"
        )

        content_type = "text"
        text_content = message.text or message.caption or ""
        file_id = None
        file_name = None

        try:
            # 1. Fotoğraf iletimi
            if message.photo:
                content_type = "photo"
                file_id = message.photo[-1].file_id
                caption = f"{header}\n📷 <b>Fotoğraf Açıklaması:</b>\n{text_content}" if text_content else header
                await bot.send_photo(
                    chat_id=settings.admin_chat_id,
                    photo=file_id,
                    caption=caption[:1024],
                    parse_mode="HTML"
                )

            # 2. Doküman (PDF vs.) iletimi
            elif message.document:
                content_type = "document"
                file_id = message.document.file_id
                file_name = message.document.file_name
                caption = f"{header}\n📄 <b>Dosya:</b> {file_name}\n<b>Açıklama:</b>\n{text_content}" if text_content else f"{header}\n📄 <b>Dosya:</b> {file_name}"
                await bot.send_document(
                    chat_id=settings.admin_chat_id,
                    document=file_id,
                    caption=caption[:1024],
                    parse_mode="HTML"
                )

            # 3. Düz Metin iletimi
            else:
                admin_text = f"{header}💬 <b>Mesaj:</b>\n{text_content}"
                await bot.send_message(
                    chat_id=settings.admin_chat_id,
                    text=admin_text,
                    parse_mode="HTML"
                )

        except Exception as e:
            print(f"[AuditService] Admin grubuna iletim hatası: {e}")

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
    async def notify_admin_event(bot: Bot, text: str, reply_markup=None):
        """
        Önemli sistem olaylarını (anlaşma, anlaşmazlık, kısıtlama, zaman aşımı) admin grubuna bildirir.
        """
        try:
            await bot.send_message(
                chat_id=settings.admin_chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[AuditService] Admin event bildirim hatası: {e}")

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
