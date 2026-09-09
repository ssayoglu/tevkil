from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from bot.config import settings
from bot.database.models import User, Listing, BridgeSession
from bot.services.redis_queue import RedisQueueService
from bot.services.audit_service import AuditService

router = Router()


def is_admin_chat(message: Message) -> bool:
    """Mesajın tanımlı Admin Denetim Grubu'ndan gelip gelmediğini kontrol eder."""
    return message.chat.id == settings.admin_chat_id


@router.message(Command("admin_yardim"))
async def cmd_admin_help(message: Message):
    if not is_admin_chat(message):
        return

    text = (
        "🛠️ <b>ADMİN DENETİM PANELİ KOMUTLARI</b>\n\n"
        "• <code>/durdur &lt;ilan_id&gt;</code>\n"
        "  Devam eden bir köprü görüşmesini anında keser ve oturumu kapatır.\n\n"
        "• <code>/kullanici_kisitla &lt;user_id&gt; [gün] [sebep]</code>\n"
        "  Kullanıcıyı belirtilen gün (varsayılan: 5) boyunca sistemden yasaklar.\n"
        "  <i>Örn: /kullanici_kisitla 12345678 5 Kural ihlali</i>\n\n"
        "• <code>/ceza_kaldir &lt;user_id&gt;</code>\n"
        "  Kullanıcının cezasını derhal kaldırır ve sistemi kullanmasına izin verir.\n\n"
        "• <code>/aktif_ilanlar</code>\n"
        "  Şu anda görüşmesi devam eden veya açık olan tüm tevkil ilanlarını listeler.\n"
    )
    await message.reply(text, parse_mode="HTML")


@router.message(Command("durdur"))
async def cmd_stop_session(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Kullanım: <code>/durdur &lt;ilan_id&gt;</code>", parse_mode="HTML")
        return

    try:
        listing_id = int(args[1])
    except ValueError:
        await message.reply("❌ Geçersiz İlan ID.")
        return

    # Oturumu bul
    s_stmt = select(BridgeSession).where(BridgeSession.listing_id == listing_id, BridgeSession.is_active == True)
    res = await db.execute(s_stmt)
    session = res.scalar_one_or_none()

    if not session:
        await message.reply(f"❌ #{listing_id} numaralı ilana ait aktif bir görüşme bulunamadı.")
        return

    session.is_active = False
    session.closed_at = datetime.utcnow()
    session.close_reason = "ADMIN_STOPPED"

    # İlanı güncelle
    l_stmt = select(Listing).where(Listing.id == listing_id)
    l_res = await db.execute(l_stmt)
    listing = l_res.scalar_one_or_none()
    if listing:
        listing.status = "CANCELLED_ADMIN"
        listing.cancellation_reason = "Yönetici müdahalesiyle durduruldu"

    await db.commit()

    # Redis köprüsünü sil
    await RedisQueueService.remove_active_bridge(session.creator_id)
    await RedisQueueService.remove_active_bridge(session.applicant_id)

    # Taraflara bilgi ver
    notice = "🛑 <b>Görüşme yöneticilerimiz tarafından denetim gereği sonlandırılmıştır.</b>"
    try:
        await message.bot.send_message(chat_id=session.creator_id, text=notice, parse_mode="HTML")
    except Exception:
        pass
    try:
        await message.bot.send_message(chat_id=session.applicant_id, text=notice, parse_mode="HTML")
    except Exception:
        pass

    await message.reply(f"✅ #{listing_id} numaralı ilanın görüşmesi başarıyla durduruldu ve taraflara bildirildi.")


@router.message(Command("kullanici_kisitla"))
async def cmd_ban_user(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        await message.reply("⚠️ Kullanım: <code>/kullanici_kisitla &lt;user_id&gt; [gün] [sebep]</code>", parse_mode="HTML")
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.reply("❌ Geçersiz kullanıcı ID.")
        return

    days = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else settings.ban_duration_days
    reason = parts[3] if len(parts) >= 4 else "Yönetici kararı ile kısıtlandı"

    ban_until = datetime.utcnow() + timedelta(days=days)

    u_stmt = select(User).where(User.id == user_id)
    res = await db.execute(u_stmt)
    user = res.scalar_one_or_none()

    if not user:
        user = User(id=user_id, is_banned=True, banned_until=ban_until, ban_reason=reason)
        db.add(user)
    else:
        user.is_banned = True
        user.banned_until = ban_until
        user.ban_reason = reason

    await db.commit()

    # Eğer aktif görüşmesi varsa köprüden çıkar
    await RedisQueueService.remove_active_bridge(user_id)

    try:
        await message.bot.send_message(
            chat_id=user_id,
            text=(
                f"⛔ <b>Sistemden Uzaklaştırıldınız</b>\n\n"
                f"Hesabınız yöneticiler tarafından <b>{days} gün</b> süreyle kısıtlanmıştır.\n"
                f"<b>Sebep:</b> {reason}"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await message.reply(
        f"🔒 <code>{user_id}</code> ID'li kullanıcı <b>{days} gün</b> boyunca kısıtlandı.\n"
        f"Bitiş Tarihi: {ban_until.strftime('%d.%m.%Y %H:%M')}",
        parse_mode="HTML"
    )


@router.message(Command("ceza_kaldir"))
async def cmd_unban_user(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Kullanım: <code>/ceza_kaldir &lt;user_id&gt;</code>", parse_mode="HTML")
        return

    try:
        user_id = int(args[1])
    except ValueError:
        await message.reply("❌ Geçersiz kullanıcı ID.")
        return

    u_stmt = select(User).where(User.id == user_id)
    res = await db.execute(u_stmt)
    user = res.scalar_one_or_none()

    if user:
        user.is_banned = False
        user.banned_until = None
        user.ban_reason = None
        await db.commit()

    try:
        await message.bot.send_message(
            chat_id=user_id,
            text="✅ Sistem kısıtlamanız yöneticiler tarafından kaldırılmıştır."
        )
    except Exception:
        pass

    await message.reply(f"🔓 <code>{user_id}</code> ID'li kullanıcının cezası kaldırıldı.", parse_mode="HTML")


@router.message(Command("aktif_ilanlar"))
async def cmd_list_active(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    stmt = select(BridgeSession).where(BridgeSession.is_active == True)
    res = await db.execute(stmt)
    sessions = res.scalars().all()

    if not sessions:
        await message.reply("ℹ️ Şu anda devam eden aktif bir tevkil görüşmesi bulunmamaktadır.")
        return

    lines = ["📋 <b>Devam Eden Aktif Görüşmeler:</b>\n"]
    for s in sessions:
        lines.append(
            f"• <b>İlan #{s.listing_id}</b> | Başlangıç: {s.started_at.strftime('%H:%M:%S')}\n"
            f"  İlan Sahibi: <code>{s.creator_id}</code>\n"
            f"  Aday: <code>{s.applicant_id}</code>\n"
            f"  İlk Mesaj Gönderildi mi: {'Evet ✅' if s.creator_first_message_sent else 'Hayır ⏳'}\n"
            f"  Durdurmak için: <code>/durdur {s.listing_id}</code>\n"
        )

    await message.reply("\n".join(lines), parse_mode="HTML")
