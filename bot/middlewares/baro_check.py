import asyncio
import re
from typing import Callable, Dict, Any, Awaitable, Optional, Tuple
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from bot.config import settings
from bot.database.models import User
from bot.services.baro_service import BaroVerificationService
from bot.services.redis_queue import redis_client


def parse_baro_and_sicil(text: str, default_baro: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Metinden Baro adı ve sicil numarasını akıllıca ayıklar."""
    if not text:
        return None, None
    clean = text.strip()

    # 1. Sadece sicil numarası girilmişse (Örn: "545" veya "545ü") ve default_baro tanımlıysa
    m_num = re.match(r"^(\d{3,7})\b", clean)
    if m_num and default_baro:
        return default_baro, m_num.group(1)

    # 2. "Mersin 545", "Mersin barosu 545", "İstanbul Barosu 34123", "Ankara 12345"
    match1 = re.search(r"([a-zA-ZçğıöşüÇĞİÖŞÜ\s0-9']+?)\s*(?:barosu|baro)?\s*[:=,-]?\s*(\d{3,7})", clean, re.IGNORECASE)
    if match1:
        candidate_baro = match1.group(1).strip()
        candidate_sicil = match1.group(2).strip()
        norm = BaroVerificationService.normalize_baro_name(candidate_baro)
        if norm:
            return norm, candidate_sicil

    # 3. "545 Mersin", "12345 İstanbul barosu"
    match2 = re.search(r"(\d{3,7})\s*(?:sicil)?\s*[:=,-]?\s*([a-zA-ZçğıöşüÇĞİÖŞÜ\s0-9']+)", clean, re.IGNORECASE)
    if match2:
        candidate_sicil = match2.group(1).strip()
        candidate_baro = match2.group(2).strip()
        norm = BaroVerificationService.normalize_baro_name(candidate_baro)
        if norm:
            return norm, candidate_sicil

    return None, None


def get_group_baro_keyboard(user_id: int, bot_username: str) -> InlineKeyboardMarkup:
    """Grup içi hızlı baro seçim butonları"""
    deep_link = f"https://t.me/{bot_username}?start=baro_verify"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏛️ İstanbul", callback_data=f"grp_baro:{user_id}:İstanbul"),
            InlineKeyboardButton(text="🏛️ Ankara", callback_data=f"grp_baro:{user_id}:Ankara"),
            InlineKeyboardButton(text="🏛️ İzmir", callback_data=f"grp_baro:{user_id}:İzmir")
        ],
        [
            InlineKeyboardButton(text="🏛️ Bursa", callback_data=f"grp_baro:{user_id}:Bursa"),
            InlineKeyboardButton(text="🏛️ Antalya", callback_data=f"grp_baro:{user_id}:Antalya"),
            InlineKeyboardButton(text="🏛️ Mersin", callback_data=f"grp_baro:{user_id}:Mersin")
        ],
        [
            InlineKeyboardButton(text="🏛️ Adana", callback_data=f"grp_baro:{user_id}:Adana"),
            InlineKeyboardButton(text="🏛️ Konya", callback_data=f"grp_baro:{user_id}:Konya"),
            InlineKeyboardButton(text="🏛️ Gaziantep", callback_data=f"grp_baro:{user_id}:Gaziantep")
        ],
        [
            InlineKeyboardButton(text="🤖 Özelden Belge / Farklı Baro Yükle", url=deep_link)
        ]
    ])


class BaroVerificationMiddleware(BaseMiddleware):
    """
    Tevkil gruplarında mesaj gönderen üyelerin Baro Levha Doğrulamasını denetler.
    Doğrulanmamış kullanıcıların mesajını anında siler, grupta susturur ve
    doğrudan grupta interaktif doğrulama konuşması yürütür.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        # Yalnızca grup ve süpergrupları denetle
        if event.chat.type not in ["group", "supergroup"]:
            return await handler(event, data)

        # Admin Denetim Grubunu muaf tut
        if event.chat.id == settings.admin_chat_id:
            return await handler(event, data)

        user = event.from_user
        if not user or user.is_bot:
            return await handler(event, data)

        # Telegram servis mesajlarını (katılma, ayrılma, sabitleme vb.) geçir
        if event.new_chat_members or event.left_chat_member or event.pinned_message:
            return await handler(event, data)

        # Grup adminlerini ve kurucuları muaf tut
        try:
            member = await event.chat.get_member(user.id)
            if member.status in ["creator", "administrator"]:
                return await handler(event, data)
        except Exception:
            pass

        db = data.get("db")
        if not db:
            return await handler(event, data)

        stmt = select(User).where(User.id == user.id)
        res = await db.execute(stmt)
        db_user = res.scalar_one_or_none()

        # Kullanıcı kayıtlı değilse veya Baro doğrulaması onaylanmamışsa
        if not db_user or not db_user.is_baro_verified:
            raw_text = (event.text or event.caption or "").strip()

            # 1. Kullanıcının daha önce seçtiği baro var mı kontrol et
            cached_baro = await redis_client.get(f"grp_baro_sel:{user.id}")

            # 2. Mesaj metninden Baro ve Sicil No tespiti dene
            parsed_baro, parsed_sicil = parse_baro_and_sicil(raw_text, default_baro=cached_baro)

            # Yetkisiz mesajı gruptan sil
            try:
                await event.delete()
            except Exception as e:
                print(f"[BaroMiddleware] Mesaj silinemedi: {e}")

            user_mention = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>{user.full_name or 'Meslektaşımız'}</a>"
            bot_info = await event.bot.get_me()
            bot_username = bot_info.username or "Tevkil_Denetim_Merkezi_bot"

            if parsed_baro and parsed_sicil:
                # Kullanıcı doğrudan baro ve sicil numarasını yazdı!
                # Kullanıcıyı DB'ye kaydet veya güncelle
                if not db_user:
                    db_user = User(
                        id=user.id,
                        username=user.username,
                        full_name=user.full_name or "",
                        rank_score=100,
                        penalty_points=0
                    )
                    db.add(db_user)
                    await db.commit()

                # Doğrulama talebini kaydet ve admin grubuna kart gönder
                submit_res = await BaroVerificationService.submit_verification_request(
                    bot=event.bot,
                    user_id=user.id,
                    baro_name=parsed_baro,
                    sicil_no=parsed_sicil,
                    db=db
                )

                await redis_client.delete(f"grp_baro_sel:{user.id}")
                last_warn_key = f"baro_warn:{event.chat.id}:{user.id}"
                old_warn_id = await redis_client.get(last_warn_key)
                if old_warn_id:
                    try:
                        await event.bot.delete_message(chat_id=event.chat.id, message_id=int(old_warn_id))
                    except Exception:
                        pass
                await redis_client.delete(last_warn_key)

                success_text = (
                    f"⏳ <b>Sayın {user_mention}, Baro Doğrulama Talebiniz Alındı!</b>\n\n"
                    f"🏛️ <b>Kayıtlı Baro:</b> {parsed_baro} Barosu\n"
                    f"🔢 <b>Sicil No:</b> <code>{parsed_sicil}</code>\n"
                    f"📌 <b>Durum:</b> <i>Yönetici Onayına Gönderildi...</i>\n\n"
                    f"✅ Yöneticilerimiz TBB Levha kontrolünü tamamladığında gruptaki mesaj yazma yetkiniz otomatik olarak açılacaktır."
                )

                try:
                    await event.bot.send_message(
                        chat_id=event.chat.id,
                        text=success_text,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    print(f"[BaroMiddleware] Grupta onay yanıtı gönderilemedi: {e}")

                return  # Handler zincirini kes

            # Bilinen gruplar listesine ekle
            from bot.services.redis_queue import RedisQueueService
            await RedisQueueService.add_known_group(event.chat.id)

            # Eski uyarı mesajı varsa sil (kirliliği önle)
            last_warn_key = f"baro_warn:{event.chat.id}:{user.id}"
            old_warn_id = await redis_client.get(last_warn_key)
            if old_warn_id:
                try:
                    await event.bot.delete_message(chat_id=event.chat.id, message_id=int(old_warn_id))
                except Exception:
                    pass

            kb = get_group_baro_keyboard(user.id, bot_username)

            warn_text = (
                f"🔒 <b>Sayın {user_mention},</b>\n\n"
                f"🏛️ Grubumuzda mesaj gönderebilmek ve tevkil ilanlarına katılabilmek için <b>Baro Levha Doğrulaması</b> yapmanız zorunludur.\n\n"
                f"👇 <b>Hızlı Doğrulama Adımları:</b>\n"
                f"1️⃣ Aşağıdaki butonlardan <b>bağlı olduğunuz baroyu seçiniz</b> veya,\n"
                f"2️⃣ Doğrudan <code>Baro Adı SicilNo</code> şeklinde yazınız (Örn: <code>Mersin 545</code> veya <code>İstanbul 12345</code>).\n\n"
                f"<i>(Doğrulama mesajınız sistem tarafından otomatik algılanıp onay kuyruğuna iletilecektir.)</i>"
            )

            try:
                sent_msg = await event.bot.send_message(
                    chat_id=event.chat.id,
                    text=warn_text,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
                if sent_msg:
                    await redis_client.set(last_warn_key, str(sent_msg.message_id), ex=600)
            except Exception as e:
                print(f"[BaroMiddleware] Grupta baro uyarı mesajı gönderilemedi: {e}")

            return  # Handler zincirini kes, yetkisiz mesaj işlenmesin

        return await handler(event, data)
