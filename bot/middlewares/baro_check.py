import asyncio
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from bot.config import settings
from bot.database.models import User


async def _delete_message_after_delay(bot, chat_id: int, message_id: int, delay_sec: int = 15):
    """Belirtilen süre sonunda mesajı gruptan otomatik siler."""
    await asyncio.sleep(delay_sec)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


class BaroVerificationMiddleware(BaseMiddleware):
    """
    Tevkil gruplarında mesaj gönderen üyelerin Baro Levha Doğrulamasını denetler.
    Doğrulanmamış kullanıcıların mesajını anında siler, grupta susturur ve
    doğrulama uyarısını doğrudan kullanıcının ÖZEL DM'ine gönderir.
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
            # 1. Yetkisiz mesajı gruptan ANINDA sil (Kimse görmesin)
            try:
                await event.delete()
            except Exception as e:
                print(f"[BaroMiddleware] Mesaj silinemedi: {e}")

            # 2. Grupta susturmayı uygula
            try:
                await event.bot.restrict_chat_member(
                    chat_id=event.chat.id,
                    user_id=user.id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False
                    )
                )
            except Exception:
                pass

            bot_info = await event.bot.get_me()
            bot_username = bot_info.username or "Tevkil_Denetim_Merkezi_bot"
            deep_link = f"https://t.me/{bot_username}?start=baro_verify"

            # 3. ÖNCELİKLE Kullanıcıya Özelden (DM) Gönder
            dm_sent = False
            try:
                dm_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⚖️ Botu Başlat & Baro Kaydını Doğrula 🎖️",
                            url=deep_link
                        )
                    ]
                ])
                dm_text = (
                    f"🔒 <b>Sayın {user.full_name or 'Meslektaşımız'},</b>\n\n"
                    f"🏛️ Hukuk Tevkil grubumuzda mesaj gönderebilmek ve ilanlara başvurabilmek için "
                    f"<b>Baro Levha Doğrulaması</b> yapmanız gerekmektedir.\n\n"
                    f"Grup düzeni gereği gruptaki mesajınız silinmiştir.\n\n"
                    f"👇 <i>Lütfen aşağıdaki butona tıklayarak kaydınızı doğrulayınız (Onaylandığında mesaj gönderme yetkiniz otomatik açılacaktır):</i>"
                )
                await event.bot.send_message(
                    chat_id=user.id,
                    text=dm_text,
                    reply_markup=dm_kb,
                    parse_mode="HTML"
                )
                dm_sent = True
            except Exception:
                dm_sent = False

            # 4. Eğer DM gönderilemediyse (Kullanıcı botu hiç başlatmamışsa):
            # Grupta kullanıcıyı etiketleyip tek seferlik buton at, 10 saniye sonra bu uyarıyı da gruptan sil.
            if not dm_sent:
                user_mention = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>{user.full_name or 'Meslektaşımız'}</a>"
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="⚖️ Botu Başlat & Avukat Doğrulaması Yap 🎖️",
                            url=deep_link
                        )
                    ]
                ])

                warn_text = (
                    f"🔒 <b>Sayın {user_mention},</b>\n\n"
                    f"🏛️ Grubumuzda mesaj gönderebilmek için <b>Baro Levha Doğrulaması</b> yapmanız gerekmektedir.\n\n"
                    f"👇 <i>Lütfen aşağıdaki butona tıklayarak botu başlatınız ve kaydınızı doğrulayınız:</i>\n\n"
                    f"⏱️ <i>(Bu bilgilendirme mesajı 10 saniye sonra otomatik silinecektir.)</i>"
                )

                try:
                    warn_msg = await event.bot.send_message(
                        chat_id=event.chat.id,
                        text=warn_text,
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                    asyncio.create_task(_delete_message_after_delay(event.bot, event.chat.id, warn_msg.message_id, delay_sec=10))
                except Exception as e:
                    print(f"[BaroMiddleware] Grupta baro uyarı mesajı gönderilemedi: {e}")

            return  # Handler zincirini kes, mesaj işlenmesin

        return await handler(event, data)
