import re
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.database.models import User, Listing
from bot.services.audit_service import AuditService

router = Router()


def is_tevkil_message(text: str) -> bool:
    if not text:
        return False
    # Türkçe büyük İ / I harflerinin Unicode combining dot tuzağını ve varyasyonlarını engelle
    normalized = (
        text.replace("İ", "i")
        .replace("I", "ı")
        .lower()
        .replace("ı", "i")
    )
    return bool(re.search(r"\btevkildir\b", normalized))


def build_apply_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Başvur (Sıraya Gir)",
                    callback_data=f"apply:{listing_id}"
                )
            ]
        ]
    )


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def detect_tevkil_post(message: Message, db: AsyncSession):
    text = message.text or message.caption
    if not text or not is_tevkil_message(text):
        return

    sender = message.from_user
    if not sender:
        return

    # 1. Kullanıcıyı DB'ye kaydet veya güncelle
    user_stmt = select(User).where(User.id == sender.id)
    res = await db.execute(user_stmt)
    user = res.scalar_one_or_none()

    if not user:
        user = User(
            id=sender.id,
            username=sender.username,
            full_name=sender.full_name or ""
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        user.username = sender.username
        user.full_name = sender.full_name or user.full_name
        await db.commit()

    # Eğer ilan sahibi kısıtlıysa ilanı işleme alma ve uyar
    if user.is_banned:
        time_str = user.banned_until.strftime("%d.%m.%Y %H:%M") if user.banned_until else ""
        await message.reply(
            f"⛔ <b>Sayın {sender.full_name},</b> hesabınız {time_str} tarihine kadar "
            f"kısıtlı olduğundan tevkil ilanı açamazsınız.",
            parse_mode="HTML"
        )
        return

    # 2. Listing kaydı oluştur
    listing = Listing(
        group_id=message.chat.id,
        group_title=message.chat.title,
        message_id=message.message_id,
        creator_id=sender.id,
        raw_text=text,
        status="OPEN",
        created_at=datetime.utcnow()
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)

    # 3. Grupta butonu içeren yanıt (reply) mesajı yayınla
    now_str = datetime.now().strftime("%H:%M:%S")
    creator_display = sender.full_name or f"@{sender.username}" if sender.username else "Meslektaşımız"
    
    reply_text = (
        f"📌 <b>Tevkil İlanı Tespit Edildi (#{listing.id})</b>\n"
        f"👤 <b>İlan Sahibi:</b> {creator_display}\n"
        f"🕒 <b>Yayın Zamanı:</b> <code>{now_str}</code>\n\n"
        f"📋 <b>Canlı Başvuru Sıralaması:</b>\n"
        f"<i>(Henüz başvuru yapılmadı. İlk tıklayan görüşme hakkı kazanır.)</i>\n\n"
        f"👇 <i>Aşağıdaki butona tıklayarak milisaniye hassasiyetli sıraya girebilirsiniz:</i>"
    )

    sent_msg = await message.reply(
        text=reply_text,
        reply_markup=build_apply_keyboard(listing.id),
        parse_mode="HTML"
    )

    listing.bot_reply_message_id = sent_msg.message_id
    await db.commit()

    # 4. Admin Denetim Grubuna bilgilendirme geç
    await AuditService.notify_admin_event(
        bot=message.bot,
        text=(
            f"📢 <b>[YENİ İLAN TESPİT EDİLDİ]</b>\n"
            f"📋 <b>İlan ID:</b> #{listing.id}\n"
            f"👥 <b>Grup:</b> {message.chat.title} (<code>{message.chat.id}</code>)\n"
            f"👤 <b>İlan Sahibi:</b> {sender.full_name} (@{sender.username or 'yok'}) [ID: <code>{sender.id}</code>]\n"
            f"📝 <b>İlan Metni:</b>\n{text[:500]}"
        )
    )
