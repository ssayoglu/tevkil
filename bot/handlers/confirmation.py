from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from bot.database.models import Listing, BridgeSession, Application, User
from bot.services.redis_queue import RedisQueueService
from bot.services.bridge_service import BridgeService
from bot.services.audit_service import AuditService

router = Router()


def get_reason_keyboard(listing_id: int, role_prefix: str) -> InlineKeyboardMarkup:
    """
    Anlaşamama sebebi seçimi klavyesi
    """
    kb = [
        [
            InlineKeyboardButton(text="💰 Ücret", callback_data=f"reason:{role_prefix}:{listing_id}:ucret"),
            InlineKeyboardButton(text="📍 Mesafe", callback_data=f"reason:{role_prefix}:{listing_id}:mesafe"),
        ],
        [
            InlineKeyboardButton(text="🎓 Kıdem", callback_data=f"reason:{role_prefix}:{listing_id}:kidem"),
            InlineKeyboardButton(text="❓ Diğer", callback_data=f"reason:{role_prefix}:{listing_id}:diger"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_next_candidate_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="✅ Kabul Ediyorum", callback_data=f"next_offer:accept:{listing_id}"),
            InlineKeyboardButton(text="❌ Reddediyorum", callback_data=f"next_offer:decline:{listing_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.callback_query(F.data.startswith("agree:"))
async def handle_agree(callback: CallbackQuery, db: AsyncSession):
    listing_id = int(callback.data.split(":")[1])
    user = callback.from_user

    stmt = select(Listing).where(Listing.id == listing_id)
    res = await db.execute(stmt)
    listing = res.scalar_one_or_none()

    if not listing or listing.creator_id != user.id:
        await callback.answer("⚠️ Sadece ilan sahibi onay verebilir.", show_alert=True)
        return

    # Aktif oturumu bul
    s_stmt = (
        select(BridgeSession)
        .where(BridgeSession.listing_id == listing_id, BridgeSession.is_active == True)
    )
    s_res = await db.execute(s_stmt)
    session = s_res.scalar_one_or_none()

    if not session:
        await callback.answer("Aktif görüşme oturumu bulunamadı.", show_alert=True)
        return

    now = datetime.utcnow()
    session.is_active = False
    session.closed_at = now
    session.close_reason = "AGREED"

    listing.status = "COMPLETED"
    listing.completed_at = now

    # Başvuru durumunu güncelle
    app_stmt = (
        update(Application)
        .where(Application.listing_id == listing_id, Application.user_id == session.applicant_id)
        .values(status="ACCEPTED")
    )
    await db.execute(app_stmt)
    await db.commit()

    # Redis köprüsünü sonlandır
    await RedisQueueService.remove_active_bridge(session.creator_id)
    await RedisQueueService.remove_active_bridge(session.applicant_id)

    # İlan sahibine bildirim
    await callback.message.edit_text(
        f"🤝 <b>Tevkil Anlaşması Tamamlandı</b>\n\n"
        f"#{listing_id} numaralı tevkil ilanı için meslektaşınız ile anlaşma sağlandığı kaydedilmiştir. "
        f"Görüşme güvenli şekilde kapatılmıştır. İyi çalışmalar dileriz.",
        parse_mode="HTML"
    )

    # Adaya bildirim
    try:
        await callback.bot.send_message(
            chat_id=session.applicant_id,
            text=(
                f"🤝 <b>Tebrikler! Tevkil Anlaşması Onaylandı</b>\n\n"
                f"#{listing_id} numaralı tevkil ilanı için ilan sahibi ile anlaşmanız teyit edildi. "
                f"Görüşme sonlandırılmıştır. Görevinizde başarılar dileriz."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    # Ana gruba sonuç bildirimi
    try:
        await callback.bot.send_message(
            chat_id=listing.group_id,
            text=(
                f"✅ <b>Tevkil Başarıyla Sonuçlandı</b>\n\n"
                f"#{listing_id} numaralı tevkil ilanı için taraflar arasında anlaşma sağlanmıştır. "
                f"İlan kapanmıştır."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    # Admin grubuna rapor
    await AuditService.notify_admin_event(
        bot=callback.bot,
        text=(
            f"✅ <b>[ANLAŞMA SAĞLANDI]</b>\n"
            f"📋 <b>İlan ID:</b> #{listing_id}\n"
            f"👤 <b>İlan Sahibi ID:</b> <code>{session.creator_id}</code>\n"
            f"👤 <b>Seçilen Aday ID:</b> <code>{session.applicant_id}</code>\n"
            f"⏰ <b>Bitiş Zamanı:</b> {now.strftime('%d.%m.%Y %H:%M')}"
        )
    )


@router.callback_query(F.data.startswith("disagree:"))
async def handle_disagree_prompt(callback: CallbackQuery, db: AsyncSession):
    listing_id = int(callback.data.split(":")[1])
    user = callback.from_user

    stmt = select(Listing).where(Listing.id == listing_id)
    res = await db.execute(stmt)
    listing = res.scalar_one_or_none()

    if not listing or listing.creator_id != user.id:
        await callback.answer("⚠️ Sadece ilan sahibi bu işlemi yapabilir.", show_alert=True)
        return

    await callback.message.edit_text(
        f"❌ <b>Anlaşamama Sebebini Belirtiniz:</b>\n\n"
        f"Lütfen meslektaşınızla anlaşamama gerekçenizi seçiniz. "
        f"Bu bilgi admin denetimine iletilecektir:",
        reply_markup=get_reason_keyboard(listing_id, role_prefix="creator"),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("reason:"))
async def handle_reason_selected(callback: CallbackQuery, db: AsyncSession):
    parts = callback.data.split(":")
    role_prefix = parts[1]
    listing_id = int(parts[2])
    reason_code = parts[3]

    reasons_map = {
        "ucret": "Ücret",
        "mesafe": "Mesafe",
        "kidem": "Kıdem",
        "diger": "Diğer"
    }
    reason_text = reasons_map.get(reason_code, "Belirtilmedi")

    # Aktif oturumu bul
    s_stmt = (
        select(BridgeSession)
        .where(BridgeSession.listing_id == listing_id, BridgeSession.is_active == True)
    )
    s_res = await db.execute(s_stmt)
    session = s_res.scalar_one_or_none()

    if not session:
        await callback.answer("Aktif oturum bulunamadı.", show_alert=True)
        return

    # Mevcut oturumu kapat
    session.is_active = False
    session.closed_at = datetime.utcnow()
    session.close_reason = f"DISAGREED_{reason_code.upper()}"

    # Başvuruyu reddedildi olarak işaretle
    app_stmt = (
        update(Application)
        .where(Application.listing_id == listing_id, Application.user_id == session.applicant_id)
        .values(status="REJECTED", disagreement_reason=reason_text)
    )
    await db.execute(app_stmt)
    await db.commit()

    # Redis köprülerini kaldır
    await RedisQueueService.remove_active_bridge(session.creator_id)
    await RedisQueueService.remove_active_bridge(session.applicant_id)

    await callback.message.edit_text(
        f"❌ <b>Görüşme Kapatıldı</b>\n\n"
        f"Gerekçe: <b>{reason_text}</b> olarak kaydedildi ve admin denetimine iletildi.",
        parse_mode="HTML"
    )

    # 1. adaya bilgi ver
    try:
        await callback.bot.send_message(
            chat_id=session.applicant_id,
            text=(
                f"ℹ️ <b>Görüşme Sonlandırıldı</b>\n\n"
                f"#{listing_id} numaralı tevkil ilanı için görüşme anlaşma sağlanamadan kapatılmıştır."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    # Admin Denetim Grubuna Detaylı Bilgi
    admin_alert = (
        f"⚠️ <b>[ANLAŞMAZLIK DEĞERLENDİRMESİ — İlan #{listing_id}]</b>\n"
        f"👤 <b>İlan Sahibi:</b> <code>{session.creator_id}</code>\n"
        f"👤 <b>Başvuran (Eski Görüşmeci):</b> <code>{session.applicant_id}</code>\n"
        f"📌 <b>İlan Sahibinin Gerekçesi:</b> {reason_text}\n\n"
        f"🛠️ <b>Admin Müdahalesi:</b>\n"
        f"• Kısıtla: <code>/kullanici_kisitla {session.applicant_id} 5</code>\n"
        f"• İletişim: Telegram ID üzerinden irtibata geçebilirsiniz."
    )
    await AuditService.notify_admin_event(callback.bot, admin_alert)

    # ŞARTNAME KURALI:
    # "Sebep 'Ücret' harici seçildiğinde otomatik olarak sıradaki 2. kişiye
    #  'Sıra size geldi, kabul ediyor musunuz?' mesajı gönderir."
    if reason_code != "ucret":
        # Sıradaki adayı getir (current_rank = 1 -> sonraki = rank 2)
        next_candidate = await RedisQueueService.get_next_available_applicant(listing_id, current_rank=1)
        if next_candidate:
            next_uid, next_score, new_rank = next_candidate
            try:
                await callback.bot.send_message(
                    chat_id=next_uid,
                    text=(
                        f"🔔 <b>Sıra Size Geldi!</b>\n\n"
                        f"#{listing_id} numaralı tevkil ilanında önceki meslektaşımız ile "
                        f"anlaşma sağlanamadığından sıra size devredilmiştir.\n\n"
                        f"Görevi devralmayı kabul ediyor musunuz?"
                    ),
                    reply_markup=get_next_candidate_keyboard(listing_id),
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"[Confirmation] Sıradaki adaya bildirim iletilemedi: {e}")
        else:
            # Yedek aday yok
            try:
                await callback.bot.send_message(
                    chat_id=session.creator_id,
                    text=f"ℹ️ #{listing_id} numaralı ilanınız için yedek sırada başka aday bulunmamaktadır."
                )
            except Exception:
                pass


@router.callback_query(F.data.startswith("next_offer:"))
async def handle_next_offer(callback: CallbackQuery, db: AsyncSession):
    parts = callback.data.split(":")
    action = parts[1]
    listing_id = int(parts[2])
    user = callback.from_user

    stmt = select(Listing).where(Listing.id == listing_id)
    res = await db.execute(stmt)
    listing = res.scalar_one_or_none()

    if not listing:
        await callback.answer("İlan bulunamadı.", show_alert=True)
        return

    if action == "accept":
        await callback.message.edit_text("🎉 Teklifi kabul ettiniz! İlan sahibiyle görüşme başlatılıyor...")
        
        # 2. sıradaki adayı aktif yap ve köprüyü kur
        app_stmt = (
            update(Application)
            .where(Application.listing_id == listing_id, Application.user_id == user.id)
            .values(status="ACTIVE")
        )
        await db.execute(app_stmt)
        await db.commit()

        await BridgeService.initiate_bridge(
            bot=callback.bot,
            listing_id=listing_id,
            creator_id=listing.creator_id,
            applicant_id=user.id,
            group_id=listing.group_id,
            candidate_rank=2
        )
    else:
        await callback.message.edit_text("İlan devir teklifini reddettiniz.")
        app_stmt = (
            update(Application)
            .where(Application.listing_id == listing_id, Application.user_id == user.id)
            .values(status="PASSED")
        )
        await db.execute(app_stmt)
        await db.commit()
