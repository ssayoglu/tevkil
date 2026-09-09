from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from bot.config import settings
from bot.database.models import Listing, BridgeSession, Application, User, PenaltyLog
from bot.services.redis_queue import RedisQueueService
from bot.services.bridge_service import BridgeService
from bot.services.audit_service import AuditService
from bot.services.rank_service import RankService
from bot.handlers.application import update_group_listing_board
from bot.utils.time_utils import format_date_short_tr

router = Router()


def get_reason_keyboard(listing_id: int, role_prefix: str) -> InlineKeyboardMarkup:
    """
    Anlaşamama sebebi seçimi klavyesi (Tarife altı ücret doğrudan ban yaptırımı içerir)
    """
    kb = [
        [
            InlineKeyboardButton(text="🚨 Tarife Altı Teklif (Direkt Ban)", callback_data=f"reason:{role_prefix}:{listing_id}:tarife_alti")
        ],
        [
            InlineKeyboardButton(text="💰 Normal Ücret", callback_data=f"reason:{role_prefix}:{listing_id}:ucret"),
            InlineKeyboardButton(text="📍 Mesafe", callback_data=f"reason:{role_prefix}:{listing_id}:mesafe"),
        ],
        [
            InlineKeyboardButton(text="🎓 Kıdem", callback_data=f"reason:{role_prefix}:{listing_id}:kidem"),
            InlineKeyboardButton(text="❓ Diğer", callback_data=f"reason:{role_prefix}:{listing_id}:diger"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_next_candidate_keyboard(listing_id: int, current_rank: int) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton(text="✅ Kabul Ediyorum", callback_data=f"next_offer:accept:{listing_id}:{current_rank}"),
            InlineKeyboardButton(text="❌ Reddediyorum", callback_data=f"next_offer:decline:{listing_id}:{current_rank}")
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

    # Aktif oturumu bul
    s_stmt = (
        select(BridgeSession)
        .where(BridgeSession.listing_id == listing_id, BridgeSession.is_active == True)
    )
    s_res = await db.execute(s_stmt)
    session = s_res.scalar_one_or_none()

    if not session:
        await callback.answer("⚠️ Bu görüşme zaten tamamlanmış veya kapatılmıştır.", show_alert=True)
        return

    if user.id not in [session.creator_id, session.applicant_id]:
        await callback.answer("⚠️ Sadece bu tevkil görüşmesinde aktif olan taraflar onay verebilir.", show_alert=True)
        return

    now = datetime.utcnow()
    session.is_active = False
    session.closed_at = now
    session.close_reason = "AGREED"

    if listing:
        listing.status = "COMPLETED"
        listing.completed_at = now

    # Başvuru durumunu güncelle
    app_stmt = (
        update(Application)
        .where(Application.listing_id == listing_id, Application.user_id == session.applicant_id)
        .values(status="ACCEPTED")
    )
    await db.execute(app_stmt)

    # Başarılı tevkil için her iki tarafa +5 rank puanı ekle
    await RankService.award_successful_tevkil(session.creator_id, session.applicant_id, db)
    await db.commit()

    # Redis köprüsünü sonlandır
    await RedisQueueService.remove_active_bridge(session.creator_id)
    await RedisQueueService.remove_active_bridge(session.applicant_id)

    # Butona basan tarafa bildirim
    try:
        await callback.message.edit_text(
            f"🤝 <b>Tevkil Anlaşması Tamamlandı</b>\n\n"
            f"#{listing_id} numaralı tevkil ilanı için meslektaşınız ile anlaşma sağlandığı onaylanmıştır. "
            f"⭐ Başarılı işlem için hesabınıza <b>+{RankService.POINTS_PER_SUCCESSFUL_TEVKIL} Rank Puanı</b> eklendi.\n"
            f"Görüşme güvenli şekilde kapatılmıştır. İyi çalışmalar dileriz.",
            parse_mode="HTML"
        )
    except Exception:
        pass

    # Diğer tarafa bildirim
    partner_id = session.applicant_id if user.id == session.creator_id else session.creator_id
    try:
        await callback.bot.send_message(
            chat_id=partner_id,
            text=(
                f"🤝 <b>Tebrikler! Tevkil Anlaşması Onaylandı</b>\n\n"
                f"#{listing_id} numaralı tevkil ilanı için meslektaşınız tarafından anlaşma teyit edildi. "
                f"⭐ Başarılı tevkil için hesabınıza <b>+{RankService.POINTS_PER_SUCCESSFUL_TEVKIL} Rank Puanı</b> eklendi.\n"
                f"Görüşme sonlandırılmıştır. Görevinizde başarılar dileriz."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    # Ana gruba sonuç bildirimi
    if listing and listing.group_id:
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

        # Gruptaki panoyu güncelle
        await update_group_listing_board(callback.bot, listing, db=db)

    # Admin grubuna rapor
    await AuditService.notify_admin_event(
        bot=callback.bot,
        text=(
            f"✅ <b>[ANLAŞMA SAĞLANDI]</b>\n"
            f"📋 <b>İlan ID:</b> #{listing_id}\n"
            f"👤 <b>İlan Sahibi ID:</b> <code>{session.creator_id}</code>\n"
            f"👤 <b>Seçilen Aday ID:</b> <code>{session.applicant_id}</code>\n"
            f"⭐ <b>Kazanılan Puan:</b> Her iki tarafa +{RankService.POINTS_PER_SUCCESSFUL_TEVKIL} Puan\n"
            f"⏰ <b>Bitiş Zamanı:</b> {now.strftime('%d.%m.%Y %H:%M')}"
        )
    )


@router.callback_query(F.data.startswith("disagree:"))
async def handle_disagree_prompt(callback: CallbackQuery, db: AsyncSession):
    listing_id = int(callback.data.split(":")[1])
    user = callback.from_user

    s_stmt = (
        select(BridgeSession)
        .where(BridgeSession.listing_id == listing_id, BridgeSession.is_active == True)
    )
    s_res = await db.execute(s_stmt)
    session = s_res.scalar_one_or_none()

    if not session:
        await callback.answer("⚠️ Bu görüşme zaten tamamlanmış veya kapatılmıştır.", show_alert=True)
        return

    if user.id not in [session.creator_id, session.applicant_id]:
        await callback.answer("⚠️ Sadece bu görüşmenin aktif tarafları anlaşamama bildirebilir.", show_alert=True)
        return

    role_prefix = "creator" if user.id == session.creator_id else "applicant"

    await callback.message.edit_text(
        f"❌ <b>Anlaşamama Sebebini Belirtiniz:</b>\n\n"
        f"Lütfen meslektaşınızla anlaşamama gerekçenizi seçiniz.\n"
        f"⚠️ <b>Önemli Kural:</b> Tarife altı ücret tekliflerinde sistem tarafından <b>DİREKT BAN</b> yaptırımı uygulanır:",
        reply_markup=get_reason_keyboard(listing_id, role_prefix=role_prefix),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("reason:"))
async def handle_reason_selected(callback: CallbackQuery, db: AsyncSession):
    parts = callback.data.split(":")
    role_prefix = parts[1]
    listing_id = int(parts[2])
    reason_code = parts[3]

    reasons_map = {
        "tarife_alti": "Tarife Altı Teklif (Kural İhlali)",
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

    current_candidate_rank = session.candidate_rank or 1

    # Mevcut oturumu kapat
    now = datetime.utcnow()
    session.is_active = False
    session.closed_at = now
    session.close_reason = f"DISAGREED_{reason_code.upper()}"

    # Başvuruyu reddedildi olarak işaretle
    app_stmt = (
        update(Application)
        .where(Application.listing_id == listing_id, Application.user_id == session.applicant_id)
        .values(status="REJECTED", disagreement_reason=reason_text)
    )
    await db.execute(app_stmt)

    # Redis köprülerini kaldır
    await RedisQueueService.remove_active_bridge(session.creator_id)
    await RedisQueueService.remove_active_bridge(session.applicant_id)

    # 🚨 ÖZEL ŞART: TARİFE ALTI ÜCRET TEKLİFİNDE DİREKT BAN YAPTIRIMI
    is_tariff_violation = (reason_code == "tarife_alti")
    if role_prefix == "creator":
        reporter_id = session.creator_id
        violator_id = session.applicant_id
        reporter_title = "İlan Sahibi"
        violator_title = f"{current_candidate_rank}. Sıra Aday"
    else:
        reporter_id = session.applicant_id
        violator_id = session.creator_id
        reporter_title = f"{current_candidate_rank}. Sıra Aday"
        violator_title = "İlan Sahibi"

    if is_tariff_violation:
        # Şikayet edilen kişiye doğrudan ban uygula
        ban_days = settings.tariff_ban_duration_days
        ban_until = now + timedelta(days=ban_days)
        
        # Kişiyi banla ve 30 ceza puanı ekle
        u_stmt = select(User).where(User.id == violator_id)
        u_res = await db.execute(u_stmt)
        violator = u_res.scalar_one_or_none()
        if violator:
            violator.is_banned = True
            violator.banned_until = ban_until
            violator.ban_reason = f"Tarife altı ücret teklifi / kural ihlali ({ban_days} gün ban)"
            violator.penalty_points += 30

            penalty_log = PenaltyLog(
                user_id=violator_id,
                points=30,
                reason="Tarife altı ücret teklifi / kural ihlali",
                issued_by="SYSTEM_TARIFF_RULE"
            )
            db.add(penalty_log)

        await db.commit()

        # Banlanan tarafa sert bildirim gönder
        try:
            await callback.bot.send_message(
                chat_id=violator_id,
                text=(
                    f"🚨 <b>DİREKT SİSTEMDEN UZAKLAŞTIRILDINIZ (TARİFE ALTI TEKLİF)</b>\n\n"
                    f"#{listing_id} numaralı tevkil görüşmesinde <b>Baro Asgari Ücret Tarifesi / Grup Tarifesi Altında</b> "
                    f"teklifte bulunulduğu tespit edilmiş/raporlanmıştır.\n\n"
                    f"📌 <b>Uygulanan Yaptırımlar:</b>\n"
                    f"• Hesabınız <b>{ban_days} gün</b> boyunca sistemden yasaklanmıştır.\n"
                    f"• Hesabınıza <b>+30 Ceza Puanı</b> eklenmiştir.\n"
                    f"• Kısıtlama Bitiş Tarihi: {format_date_short_tr(ban_until)}\n\n"
                    f"<i>Meslek onuruna ve baro asgari ücret tarifelerine uyulması zorunludur.</i>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[Confirmation] Tarife ban bildirimi iletilemedi: {e}")

        # Bildiren tarafa onay
        await callback.message.edit_text(
            f"🚨 <b>Tarife İhlali Kaydedildi ve Yaptırım Uygulandı</b>\n\n"
            f"Tarife altı teklif bildirimi nedeniyle karşı taraf <b>{ban_days} gün süreyle doğrudan banlanmış</b> "
            f"ve durum Admin Denetim Grubu'na yüksek öncelikle iletilmiştir.",
            parse_mode="HTML"
        )

        # Admin Denetim Grubuna Yüksek Öncelikli Alarm
        admin_alert = (
            f"🚨🚨 <b>[TARİFE ALTI ÜCRET İHLALİ — DİREKT BAN UYGULANDI]</b>\n"
            f"📋 <b>İlan ID:</b> #{listing_id}\n"
            f"👤 <b>Şikayet Eden ({reporter_title}):</b> <code>{reporter_id}</code>\n"
            f"👤 <b>Yasaklanan ({violator_title}):</b> <code>{violator_id}</code>\n"
            f"⚖️ <b>Uygulanan Ceza:</b> {ban_days} Gün Direkt Ban & +30 Ceza Puanı\n"
            f"⏰ <b>Bitiş Tarihi:</b> {format_date_short_tr(ban_until)}\n\n"
            f"<i>Yöneticilerimiz sohbet arşivini yukarıdaki loglardan denetleyebilir.</i>"
        )
        await AuditService.notify_admin_event(callback.bot, admin_alert)

    else:
        await db.commit()
        await callback.message.edit_text(
            f"❌ <b>Görüşme Kapatıldı</b>\n\n"
            f"Gerekçe: <b>{reason_text}</b> olarak kaydedildi ve admin denetimine iletildi.",
            parse_mode="HTML"
        )

        # Karşı tarafa bilgi ver
        partner_id = session.applicant_id if callback.from_user.id == session.creator_id else session.creator_id
        try:
            await callback.bot.send_message(
                chat_id=partner_id,
                text=(
                    f"ℹ️ <b>Görüşme Sonlandırıldı</b>\n\n"
                    f"#{listing_id} numaralı tevkil ilanı için görüşme meslektaşınız tarafından ({reason_text}) gerekçesiyle kapatılmıştır."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

        # Admin Denetim Grubuna Detaylı Bilgi
        admin_alert = (
            f"⚠️ <b>[ANLAŞMAZLIK DEĞERLENDİRMESİ — İlan #{listing_id}]</b>\n"
            f"👤 <b>İlan Sahibi:</b> <code>{session.creator_id}</code>\n"
            f"👤 <b>Başvuran ({current_candidate_rank}. Sıra Aday):</b> <code>{session.applicant_id}</code>\n"
            f"📌 <b>Bildiren:</b> {reporter_title} | <b>Gerekçe:</b> {reason_text}\n\n"
            f"🛠️ <b>Admin Müdahalesi:</b>\n"
            f"• Kısıtla: <code>/kullanici_kisitla {violator_id} 5</code>\n"
            f"• Ceza Puanı: <code>/ceza_puani_ver {violator_id} 10 Anlaşmazlık ihlali</code>"
        )
        await AuditService.notify_admin_event(callback.bot, admin_alert)

    # İlanı veritabanından yeniden çek ve panoyu güncelle
    l_stmt = select(Listing).where(Listing.id == listing_id)
    l_res = await db.execute(l_stmt)
    listing = l_res.scalar_one_or_none()
    if listing:
        await update_group_listing_board(callback.bot, listing, db=db)

    # ŞARTNAME KURALI:
    # "Sebep 'Ücret' harici seçildiğinde otomatik olarak sıradaki kişiye
    #  'Sıra size geldi, kabul ediyor musunuz?' mesajı gönderir."
    # (Tarife ihlali durumunda da ilan sahibine yeni aday önerilebilir)
    if reason_code not in ["ucret"]:
        # Sıradaki adayı getir (current_candidate_rank sonrasındaki ilk aday)
        next_candidate = await RedisQueueService.get_next_available_applicant(listing_id, current_rank=current_candidate_rank)
        if next_candidate:
            next_uid, next_score, new_rank = next_candidate

            # Aday bilgilerini çek (etiketlemek için)
            cand_stmt = select(User).where(User.id == next_uid)
            cand_res = await db.execute(cand_stmt)
            cand_user = cand_res.scalar_one_or_none()

            cand_mention = f"@{cand_user.username}" if (cand_user and cand_user.username) else (f"<a href='tg://user?id={next_uid}'>{cand_user.full_name if cand_user else 'Meslektaşımız'}</a>")

            # 1. Ana grupta 2. kişiyi etiketleyerek bildirim yayınla
            if listing and listing.group_id:
                try:
                    next_cand_group_kb = InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="💬 İlan Sahibine Yaz (Görüşmeyi Başlat)",
                                    url=f"https://t.me/Tevkil_Denetim_Merkezi_bot?start=chat_{listing_id}"
                                )
                            ]
                        ]
                    )
                    await callback.bot.send_message(
                        chat_id=listing.group_id,
                        text=(
                            f"📢 <b>[SIRA SİZE GELDİ — İlan #{listing_id}]</b>\n\n"
                            f"🔔 Sayın {cand_mention}:\n"
                            f"Önceki meslektaşımız ile anlaşma sağlanamadığından <b>{new_rank}. sıradaki aday olarak görüşme hakkı size geçmiştir!</b>\n\n"
                            f"👇 İlan sahibi ile görüşmeye başlamak için lütfen aşağıdaki butona tıklayınız:"
                        ),
                        reply_markup=next_cand_group_kb,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    print(f"[Confirmation] Gruba sıradaki aday etiket bildirimi gönderilemedi: {e}")

            # 2. DM'den de onay mesajı gönder
            try:
                await callback.bot.send_message(
                    chat_id=next_uid,
                    text=(
                        f"🔔 <b>Sıra Size Geldi! (#{listing_id})</b>\n\n"
                        f"#{listing_id} numaralı tevkil ilanında önceki meslektaşımız ile "
                        f"anlaşma sağlanamadığından sıra <b>{new_rank}. sıradaki aday olarak size</b> devredilmiştir.\n\n"
                        f"Görevi devralmayı kabul ediyor musunuz?"
                    ),
                    reply_markup=get_next_candidate_keyboard(listing_id, current_rank=new_rank),
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"[Confirmation] Sıradaki adaya DM bildirimi iletilemedi: {e}")
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
    target_rank = int(parts[3]) if len(parts) >= 4 else 2
    user = callback.from_user

    stmt = select(Listing).where(Listing.id == listing_id)
    res = await db.execute(stmt)
    listing = res.scalar_one_or_none()

    if not listing:
        await callback.answer("İlan bulunamadı.", show_alert=True)
        return

    if action == "accept":
        await callback.message.edit_text(f"🎉 Teklifi kabul ettiniz! İlan sahibiyle görüşme başlatılıyor...")
        
        # Adayı aktif yap ve köprüyü kur
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
            candidate_rank=target_rank
        )
        await update_group_listing_board(callback.bot, listing, db=db)

    else:
        await callback.message.edit_text("İlan devir teklifini reddettiniz.")
        app_stmt = (
            update(Application)
            .where(Application.listing_id == listing_id, Application.user_id == user.id)
            .values(status="PASSED")
        )
        await db.execute(app_stmt)
        await db.commit()
        await update_group_listing_board(callback.bot, listing, db=db)

        # Zincirleme devir: Sıradaki bir sonraki adaya git (target_rank + 1)
        next_candidate = await RedisQueueService.get_next_available_applicant(listing_id, current_rank=target_rank)
        if next_candidate:
            next_uid, next_score, new_rank = next_candidate
            try:
                await callback.bot.send_message(
                    chat_id=next_uid,
                    text=(
                        f"🔔 <b>Sıra Size Geldi! (#{listing_id})</b>\n\n"
                        f"#{listing_id} numaralı tevkil ilanında önceki aday teklifi reddettiğinden "
                        f"sıra <b>{new_rank}. sıradaki aday olarak size</b> devredilmiştir.\n\n"
                        f"Görevi devralmayı kabul ediyor musunuz?"
                    ),
                    reply_markup=get_next_candidate_keyboard(listing_id, current_rank=new_rank),
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"[Confirmation] Zincirleme sıradaki adaya teklif iletilemedi: {e}")
        else:
            try:
                await callback.bot.send_message(
                    chat_id=listing.creator_id,
                    text=f"ℹ️ #{listing_id} numaralı ilanınız için sıradaki adaylar teklifi reddetti ve yedek sırada başka aday kalmadı."
                )
            except Exception:
                pass
