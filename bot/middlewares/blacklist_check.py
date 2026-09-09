from typing import Callable, Dict, Any, Awaitable
from datetime import datetime
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject, ChatPermissions
from sqlalchemy import select
from bot.database.models import User


class BlacklistMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        db = data.get("db")
        user = None

        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if not user or not db:
            return await handler(event, data)

        stmt = select(User).where(User.id == user.id)
        res = await db.execute(stmt)
        db_user = res.scalar_one_or_none()

        if db_user and db_user.is_banned:
            now = datetime.utcnow()
            if db_user.banned_until and db_user.banned_until > now:
                # Kullanıcı hâlâ kısıtlı
                time_str = db_user.banned_until.strftime("%d.%m.%Y %H:%M")
                warn_msg = (
                    f"⛔ <b>Erişim Kısıtlaması:</b> Hesabınız <b>{time_str}</b> tarihine kadar "
                    f"sistemden geçici olarak kısıtlanmıştır.\n"
                    f"<b>Gerekçe:</b> {db_user.ban_reason or 'Kural ihlali'}"
                )
                if isinstance(event, CallbackQuery):
                    await event.answer("⛔ Hesabınız geçici olarak kısıtlanmıştır.", show_alert=True)
                elif isinstance(event, Message):
                    if event.chat.type == "private":
                        await event.reply(warn_msg, parse_mode="HTML")
                    elif event.chat.type in ["group", "supergroup"]:
                        # Gruptan mesaj atmasını engelle: Mesajı sil ve Telegram grubunda sustur
                        try:
                            await event.delete()
                        except Exception:
                            pass

                        try:
                            await event.bot.restrict_chat_member(
                                chat_id=event.chat.id,
                                user_id=user.id,
                                permissions=ChatPermissions(
                                    can_send_messages=False,
                                    can_send_media_messages=False,
                                    can_send_other_messages=False,
                                    can_add_web_page_previews=False
                                ),
                                until_date=db_user.banned_until
                            )
                        except Exception:
                            pass
                return  # İşlemi kes

            elif db_user.banned_until and db_user.banned_until <= now:
                # Süre dolmuş, otomatik ceza kaldır
                db_user.is_banned = False
                db_user.banned_until = None
                db_user.ban_reason = None
                await db.commit()

                # Grupta susturmayı kaldır
                if isinstance(event, Message) and event.chat.type in ["group", "supergroup"]:
                    try:
                        await event.bot.restrict_chat_member(
                            chat_id=event.chat.id,
                            user_id=user.id,
                            permissions=ChatPermissions(
                                can_send_messages=True,
                                can_send_media_messages=True,
                                can_send_other_messages=True,
                                can_add_web_page_previews=True
                            )
                        )
                    except Exception:
                        pass

        return await handler(event, data)
