from typing import Optional, Dict, Any
from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, update
from bot.database.connection import AsyncSessionLocal
from bot.database.models import BridgeSession, Listing
from bot.services.redis_queue import RedisQueueService
from bot.services.audit_service import AuditService
from bot.services.timeout_service import TimeoutService
from datetime import datetime


def get_confirmation_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    """
    İlan sahibinin ekranındaki [Anlaştık] ve [Anlaşamadık] butonları
    """
    kb = [
        [
            InlineKeyboardButton(text="🤝 Anlaştık", callback_data=f"agree:{listing_id}"),
            InlineKeyboardButton(text="❌ Anlaşamadık", callback_data=f"disagree:{listing_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


class BridgeService:
    @staticmethod
    async def initiate_bridge(
        bot: Bot,
        listing_id: int,
        creator_id: int,
        applicant_id: int,
        group_id: int,
        candidate_rank: int = 1
    ) -> BridgeSession:
        """
        İlan sahibi ile sıradaki aday arasında anonim köprü oturumunu başlatır.
        """
        async with AsyncSessionLocal() as db:
            session = BridgeSession(
                listing_id=listing_id,
                creator_id=creator_id,
                applicant_id=applicant_id,
                is_active=True,
                started_at=datetime.utcnow()
            )
            db.add(session)

            # İlan durumunu MATCHED yap
            listing_stmt = select(Listing).where(Listing.id == listing_id)
            res = await db.execute(listing_stmt)
            listing = res.scalar_one_or_none()
            if listing:
                listing.status = "MATCHED"
                listing.matched_at = datetime.utcnow()

            await db.commit()
            await db.refresh(session)
            session_id = session.id

        # Redis üzerinde her iki kullanıcı için aktif oturum aç
        creator_bridge_data = {
            "listing_id": listing_id,
            "session_id": session_id,
            "partner_id": applicant_id,
            "role": "CREATOR",
            "candidate_rank": candidate_rank,
            "group_id": group_id
        }
        applicant_bridge_data = {
            "listing_id": listing_id,
            "session_id": session_id,
            "partner_id": creator_id,
            "role": "APPLICANT",
            "candidate_rank": candidate_rank,
            "group_id": group_id
        }

        await RedisQueueService.set_active_bridge(creator_id, creator_bridge_data)
        await RedisQueueService.set_active_bridge(applicant_id, applicant_bridge_data)

        # 30 Dakikalık zaman aşımı görevini başlat
        TimeoutService.start_timeout_watcher(
            bot=bot,
            listing_id=listing_id,
            session_id=session_id,
            creator_id=creator_id,
            applicant_id=applicant_id,
            group_id=group_id
        )

        # Şartnamedeki Süreç Başlatma Mesajları:
        # İlan Sahibine:
        try:
            await bot.send_message(
                chat_id=creator_id,
                text=(
                    f"📌 <b>#{listing_id} Numaralı Tevkil İlanınız İçin {candidate_rank}. Sıra Başvurusu Alındı.</b>\n\n"
                    f"⚠️ <i>Lütfen görevin detaylarını yazarak iletişimi başlatın.</i>\n\n"
                    f"⏳ <b>Önemli Kural:</b> İlk mesajı <b>30 dakika</b> içerisinde iletmeniz gerekmektedir, "
                    f"aksi halde ilanınız iptal edilecek ve hesabınız 5 gün kısıtlanacaktır.\n\n"
                    f"Görüşme tamamlandığında aşağıdaki butonlardan durumu teyit edebilirsiniz:"
                ),
                reply_markup=get_confirmation_keyboard(listing_id),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[BridgeService] İlan sahibine başlatma mesajı gönderilemedi: {e}")

        # Adaya:
        try:
            await bot.send_message(
                chat_id=applicant_id,
                text=(
                    f"🎉 <b>Tevkil İçin {candidate_rank}. Sıradan Seçildiniz.</b>\n\n"
                    f"İlan sahibi detayları ilettiğinde size buradan ulaştırılacaktır. "
                    f"Tüm mesajlar, fotoğraflar ve PDF dosyaları bu sohbet üzerinden anonim olarak iletilir."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[BridgeService] Adaya başlatma mesajı gönderilemedi: {e}")

        # Admin grubuna bildirim
        await AuditService.notify_admin_event(
            bot,
            f"🔗 <b>[KÖPRÜ BAŞLATILDI — İlan #{listing_id}]</b>\n"
            f"👤 İlan Sahibi ID: <code>{creator_id}</code>\n"
            f"👤 {candidate_rank}. Sıra Aday ID: <code>{applicant_id}</code>\n"
            f"⏱️ 30 dakikalık ilk mesaj süresi başladı."
        )

        return session

    @staticmethod
    async def forward_bridge_message(bot: Bot, sender_msg: Message, bridge_info: Dict[str, Any]):
        """
        DM'den gelen mesajı anonimleştirip partnerine iletir, loglar ve admin grubuna klonlar.
        """
        listing_id = bridge_info["listing_id"]
        session_id = bridge_info["session_id"]
        partner_id = bridge_info["partner_id"]
        role = bridge_info["role"]
        candidate_rank = bridge_info.get("candidate_rank", 1)

        sender_user = sender_msg.from_user
        sender_id = sender_user.id
        sender_name = sender_user.full_name
        sender_uname = sender_user.username

        # İlan sahibi ilk mesajını atıyorsa flag'i güncelle
        if role == "CREATOR":
            async with AsyncSessionLocal() as db:
                stmt = (
                    update(BridgeSession)
                    .where(BridgeSession.id == session_id, BridgeSession.creator_first_message_sent == False)
                    .values(creator_first_message_sent=True, first_message_at=datetime.utcnow())
                )
                await db.execute(stmt)
                await db.commit()

        # Anonim Etiketler
        if role == "CREATOR":
            sender_tag = "💼 <b>[İlan Sahibi]</b>"
            sender_role_str = "İlan Sahibi"
            target_role_str = f"{candidate_rank}. Sıra Aday"
        else:
            sender_tag = f"⚖️ <b>[{candidate_rank}. Sıra Başvuran Aday]</b>"
            sender_role_str = f"{candidate_rank}. Sıra Aday"
            target_role_str = "İlan Sahibi"

        # 1. Partner'a Anonim İletim
        text_body = sender_msg.text or sender_msg.caption or ""
        
        try:
            if sender_msg.photo:
                photo_id = sender_msg.photo[-1].file_id
                cap = f"{sender_tag}\n\n{text_body}" if text_body else sender_tag
                await bot.send_photo(chat_id=partner_id, photo=photo_id, caption=cap[:1024], parse_mode="HTML")
            elif sender_msg.document:
                doc_id = sender_msg.document.file_id
                cap = f"{sender_tag}\n\n{text_body}" if text_body else sender_tag
                await bot.send_document(chat_id=partner_id, document=doc_id, caption=cap[:1024], parse_mode="HTML")
            elif sender_msg.text:
                full_msg = f"{sender_tag}\n\n{text_body}"
                await bot.send_message(chat_id=partner_id, text=full_msg, parse_mode="HTML")
            else:
                await sender_msg.reply("⚠️ Sadece metin, fotoğraf ve PDF/belge gönderimi desteklenmektedir.")
                return
        except Exception as e:
            print(f"[BridgeService] Mesaj partnere iletilemedi: {e}")
            await sender_msg.reply("❌ Mesaj karşı tarafa ulaştırılamadı.")
            return

        # 2. Admin Denetim Grubuna ve DB'ye anlık loglama
        await AuditService.log_and_forward_to_admin(
            bot=bot,
            listing_id=listing_id,
            session_id=session_id,
            sender_id=sender_id,
            sender_name=sender_name,
            sender_username=sender_uname,
            sender_role=sender_role_str,
            target_role=target_role_str,
            message=sender_msg
        )
