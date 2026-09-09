from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, update
from bot.config import settings
from bot.database.connection import AsyncSessionLocal
from bot.database.models import BridgeSession, Listing
from bot.services.redis_queue import RedisQueueService
from bot.services.audit_service import AuditService
from bot.services.timeout_service import TimeoutService


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
        now = datetime.utcnow()
        timeout_at = now + timedelta(minutes=settings.timeout_minutes)

        async with AsyncSessionLocal() as db:
            session = BridgeSession(
                listing_id=listing_id,
                creator_id=creator_id,
                applicant_id=applicant_id,
                candidate_rank=candidate_rank,
                is_active=True,
                started_at=now,
                timeout_at=timeout_at
            )
            db.add(session)

            # İlan durumunu MATCHED yap
            listing_stmt = select(Listing).where(Listing.id == listing_id)
            res = await db.execute(listing_stmt)
            listing = res.scalar_one_or_none()
            if listing:
                listing.status = "MATCHED"
                listing.matched_at = now

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

        # 1. Ana Grupta "Görüşme Başladı / İlan Sahibine Yaz" Duyurusu ve Butonları
        if group_id:
            try:
                group_contact_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="💬 İlan Sahibine Yaz (1. Sıra Aday)",
                                url="https://t.me/Tevkil_Denetim_Merkezi_bot?start=1"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="💼 Adayla Görüş (İlan Sahibi)",
                                url="https://t.me/Tevkil_Denetim_Merkezi_bot?start=1"
                            )
                        ]
                    ]
                )
                await bot.send_message(
                    chat_id=group_id,
                    text=(
                        f"📢 <b>[BAŞVURU ALINDI — İlan #{listing_id}]</b>\n\n"
                        f"🟢 <b>{candidate_rank}. sıradaki meslektaşımız</b> ilana başvurdu ve görüşme hakkı kazandı.\n\n"
                        f"👇 <b>Görüşmeyi Başlatmak İçin:</b>\n"
                        f"• <b>1. Sıradaki Aday:</b> <code>İlan Sahibine Yaz</code> butonuna tıklayınız.\n"
                        f"• <b>İlan Sahibi:</b> <code>Adayla Görüş</code> butonuna tıklayınız.\n\n"
                        f"<i>(Görüşmeler bot üzerinden anonim ve güvenli olarak yürütülür.)</i>"
                    ),
                    reply_markup=group_contact_kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"[BridgeService] Gruba görüşme başladı duyurusu iletilemedi: {e}")

        # 2. İlan Sahibine DM Bildirimi
        try:
            await bot.send_message(
                chat_id=creator_id,
                text=(
                    f"📌 <b>#{listing_id} Numaralı Tevkil İlanınız İçin {candidate_rank}. Sıra Başvurusu Alındı.</b>\n\n"
                    f"⚠️ <i>Lütfen görevin detaylarını buraya yazarak iletişimi başlatın.</i>\n\n"
                    f"⏳ <b>Önemli Kural:</b> İlk mesajı <b>30 dakika</b> içerisinde iletmeniz gerekmektedir, "
                    f"aksi halde ilanınız iptal edilecek, hesabınıza +20 Ceza Puanı eklenecek ve 5 gün kısıtlanacaktır.\n\n"
                    f"🛡️ <b>Güvenlik Uyarısı:</b> Gruptan profilinize tıklayıp 'hemen yaparım' diyerek "
                    f"özelden yazanları dikkate almayınız. Tüm süreci bu bot üzerinden yürütünüz.\n\n"
                    f"Görüşme tamamlandığında aşağıdaki butonlardan durumu teyit edebilirsiniz:"
                ),
                reply_markup=get_confirmation_keyboard(listing_id),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[BridgeService] İlan sahibine başlatma mesajı gönderilemedi (Kullanıcı botu başlatmamış olabilir): {e}")

        # 3. Adaya DM Bildirimi (Anlaştık / Anlaşamadık butonlarıyla birlikte)
        try:
            await bot.send_message(
                chat_id=applicant_id,
                text=(
                    f"🎉 <b>Tevkil İçin {candidate_rank}. Sıradan Seçildiniz. (İlan #{listing_id})</b>\n\n"
                    f"İlan sahibi meslektaşımız ile anonim görüşme kanalınız açılmıştır.\n"
                    f"💬 Buradan yazacağınız tüm mesajlar, fotoğraflar, ses kayıtları ve PDF dosyaları anonim olarak iletilir.\n\n"
                    f"Görüşme tamamlandığında veya vazgeçmek istediğinizde aşağıdaki butonları kullanabilirsiniz:"
                ),
                reply_markup=get_confirmation_keyboard(listing_id),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[BridgeService] Adaya başlatma mesajı gönderilemedi (Kullanıcı botu başlatmamış olabilir): {e}")

        # 4. Admin grubuna bildirim
        await AuditService.notify_admin_event(
            bot,
            f"🔗 <b>[KÖPRÜ BAŞLATILDI — İlan #{listing_id}]</b>\n"
            f"👤 İlan Sahibi ID: <code>{creator_id}</code>\n"
            f"👤 {candidate_rank}. Sıra Aday ID: <code>{applicant_id}</code>\n"
            f"⏱️ 30 dakikalık ilk mesaj süresi başladı."
        )

        return session

    @staticmethod
    async def flush_pending_messages(bot: Bot, user_id: int):
        """
        Kullanıcı bota girdiğinde kuyrukta bekleyen tüm mesajları kendisine iletir.
        """
        pending = await RedisQueueService.pop_all_pending_messages(user_id)
        if not pending:
            return

        for p in pending:
            try:
                mtype = p.get("type")
                if mtype == "text":
                    await bot.send_message(chat_id=user_id, text=p["text"], parse_mode="HTML")
                elif mtype == "photo":
                    await bot.send_photo(chat_id=user_id, photo=p["file_id"], caption=p.get("caption"), parse_mode="HTML")
                elif mtype == "document":
                    await bot.send_document(chat_id=user_id, document=p["file_id"], caption=p.get("caption"), parse_mode="HTML")
                elif mtype == "voice":
                    await bot.send_voice(chat_id=user_id, voice=p["file_id"], caption=p.get("caption"), parse_mode="HTML")
            except Exception as e:
                print(f"[BridgeService] Kuyruktaki mesaj iletilemedi: {e}")

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

        # 1. Partner'a Anonim İletim veya Kuyruğa Alma
        text_body = sender_msg.text or sender_msg.caption or ""
        msg_delivered = False
        payload = None

        try:
            if sender_msg.photo:
                photo_id = sender_msg.photo[-1].file_id
                cap = f"{sender_tag}\n\n{text_body}" if text_body else sender_tag
                payload = {"type": "photo", "file_id": photo_id, "caption": cap[:1024]}
                await bot.send_photo(chat_id=partner_id, photo=photo_id, caption=cap[:1024], parse_mode="HTML")
                msg_delivered = True
            elif sender_msg.document:
                doc_id = sender_msg.document.file_id
                cap = f"{sender_tag}\n\n{text_body}" if text_body else sender_tag
                payload = {"type": "document", "file_id": doc_id, "caption": cap[:1024]}
                await bot.send_document(chat_id=partner_id, document=doc_id, caption=cap[:1024], parse_mode="HTML")
                msg_delivered = True
            elif sender_msg.voice:
                voice_id = sender_msg.voice.file_id
                cap = f"{sender_tag}\n\n{text_body}" if text_body else sender_tag
                payload = {"type": "voice", "file_id": voice_id, "caption": cap[:1024]}
                await bot.send_voice(chat_id=partner_id, voice=voice_id, caption=cap[:1024], parse_mode="HTML")
                msg_delivered = True
            elif sender_msg.text:
                full_msg = f"{sender_tag}\n\n{text_body}"
                payload = {"type": "text", "text": full_msg}
                await bot.send_message(chat_id=partner_id, text=full_msg, parse_mode="HTML")
                msg_delivered = True
            else:
                await sender_msg.reply("⚠️ Sadece metin, fotoğraf, ses kaydı ve PDF/belge gönderimi desteklenmektedir.")
                return
        except Exception as e:
            print(f"[BridgeService] Mesaj anlık iletilemedi, kuyruğa alınıyor: {e}")
            if payload:
                await RedisQueueService.push_pending_message(partner_id, payload)
                await sender_msg.reply(
                    "⏳ <b>Mesajınız Güvenle Alındı ve Kuyruğa Eklendi.</b>\n\n"
                    "Karşı taraf bot penceresini açtığı an tüm mesajlarınız sırasıyla kendisine iletilecektir.",
                    parse_mode="HTML"
                )

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
