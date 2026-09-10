from typing import Optional
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove, Message
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
            InlineKeyboardButton(text="🚨 Tarife Altı Teklif (Direkt Uzaklaştırma)", callback_data=f"reason:{role_prefix}:{listing_id}:tarife_alti")
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


def get_disagreement_admin_keyboard(creator_id: int, applicant_id: int, listing_id: int = 0) -> InlineKeyboardMarkup:
    lid_suffix = f":{listing_id}" if listing_id else ""
    buttons = [
        [
            InlineKeyboardButton(text="⛔ Adayı Uzaklaştır (5G)", callback_data=f"adm_act:ban:{applicant_id}:5{lid_suffix}"),
            InlineKeyboardButton(text="⛔ İlan Sahibini Uzaklaştır (5G)", callback_data=f"adm_act:ban:{creator_id}:5{lid_suffix}")
        ],
        [
            InlineKeyboardButton(text="⚠️ Adaya +10 Ceza", callback_data=f"adm_act:penalty:{applicant_id}:10{lid_suffix}"),
            InlineKeyboardButton(text="⚠️ İlan Sahibine +10 Ceza", callback_data=f"adm_act:penalty:{creator_id}:10{lid_suffix}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def execute_agree_step(
    bot,
    user_id: int,
    listing_id: int,
    db: AsyncSession,
    callback: Optional[CallbackQuery] = None,
    message: Optional[Message] = None
):
    """
    Hem inline callback butonundan hem de DM metin/komut tetikleyicilerinden
    çağrılabilen çift taraflı anlaşma doğrulama ve sonuçlandırma fonksiyonu.
    """
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
        msg_text = "⚠️ Bu görüşme zaten tamamlanmış veya kapatılmıştır."
        if callback:
            await callback.answer(msg_text, show_alert=True)
        elif message:
            await message.reply(msg_text)
        return

    if user_id not in [session.creator_id, session.applicant_id]:
        msg_text = "⚠️ Sadece bu tevkil görüşmesinde aktif olan taraflar onay verebilir."
        if callback:
            await callback.answer(msg_text, show_alert=True)
        elif message:
            await message.reply(msg_text)
        return

    if callback:
        await callback.answer()

    is_creator = (user_id == session.creator_id)
    if is_creator:
        session.creator_agreed = True
    else:
        session.applicant_agreed = True

    await db.commit()

    # ÇİFT TARAFLI ONAY KONTROLÜ: Her iki taraf da [Anlaştık] dedi mi?
    both_agreed = (session.creator_agreed and session.applicant_agreed)

    if both_agreed:
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

        # Onaylayan tarafa bildirim + persistent menüyü kaldır
        user_success_text = (
            f"🤝 <b>Tevkil Anlaşması Karşılıklı Onaylandı!</b>\n\n"
            f"#{listing_id} numaralı tevkil ilanı için her iki meslektaşımız da anlaşmayı teyit etmiştir.\n"
            f"⭐ Başarılı işlem için hesabınıza <b>+{RankService.POINTS_PER_SUCCESSFUL_TEVKIL} Rank Puanı</b> eklendi.\n"
            f"Görüşme güvenli şekilde tamamlanmıştır. İyi çalışmalar dileriz."
        )
        try:
            if callback and callback.message:
                await callback.message.edit_text(user_success_text, parse_mode="HTML")
                await bot.send_message(
                    chat_id=user_id,
                    text="✨ <i>Görüşme başarıyla tamamlandı.</i>",
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="HTML"
                )
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=user_success_text,
                    reply_markup=ReplyKeyboardRemove(),
                    parse_mode="HTML"
                )
        except Exception:
            pass

        # Diğer tarafa bildirim + persistent menüyü kaldır
        partner_id = session.applicant_id if is_creator else session.creator_id
        try:
            await bot.send_message(
                chat_id=partner_id,
                text=(
                    f"🤝 <b>Tebrikler! Tevkil Anlaşması Karşılıklı Onaylandı!</b>\n\n"
                    f"#{listing_id} numaralı tevkil ilanı için meslektaşınız da anlaşmayı teyit etti.\n"
                    f"⭐ Başarılı tevkil için hesabınıza <b>+{RankService.POINTS_PER_SUCCESSFUL_TEVKIL} Rank Puanı</b> eklendi.\n"
                    f"Görüşme tamamlanmıştır. Görevinizde başarılar dileriz."
                ),
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
        except Exception:
            pass

        # Ana gruba sonuç bildirimi
        if listing and listing.group_id:
            try:
                await bot.send_message(
                    chat_id=listing.group_id,
                    text=(
                        f"✅ <b>Tevkil Başarıyla Sonuçlandı</b>\n\n"
                        f"#{listing_id} numaralı tevkil ilanı için taraflar arasında karşılıklı anlaşma sağlanmıştır. "
                        f"İlan kapanmıştır."
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass

            # Gruptaki panoyu güncelle
            await update_group_listing_board(bot, listing, db=db)

        # Admin grubuna rapor
        await AuditService.notify_admin_event(
            bot=bot,
            text=(
                f"✅ <b>[KARŞILIKLI ANLAŞMA SAĞLANDI]</b>\n"
                f"📋 <b>İlan ID:</b> #{listing_id}\n"
                f"👤 <b>İlan Sahibi ID:</b> <code>{session.creator_id}</code>\n"
                f"👤 <b>Seçilen Aday ID:</b> <code>{session.applicant_id}</code>\n"
                f"⭐ <b>Kazanılan Puan:</b> Her iki tarafa +{RankService.POINTS_PER_SUCCESSFUL_TEVKIL} Puan\n"
                f"⏰ <b>Bitiş Zamanı:</b> {now.strftime('%d.%m.%Y %H:%M')}"
            ),
            listing_id=listing_id
        )

    else:
        # Tek taraf onayladı, karşı tarafın onayı bekleniyor
        partner_id = session.applicant_id if is_creator else session.creator_id
        wait_text = (
            f"⏳ <b>Anlaşma Onayınız Alındı</b>\n\n"
            f"#{listing_id} numaralı tevkil için anlaşma teyidiniz sisteme kaydedildi.\n"
            f"ℹ️ Sürecin tamamlanıp puanların tanımlanması için <b>karşı meslektaşımızın da [🤝 Anlaştık] butonuna basması bekleniyor...</b>\n\n"
            f"<i>Fikriniz değişirse veya anlaşmazlık çıkarsa iptal edebilirsiniz:</i>"
        )
        wait_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="❌ Anlaşamadık / İptal Et", callback_data=f"disagree:{listing_id}")
                ]
            ]
        )
        try:
            if callback and callback.message:
                await callback.message.edit_text(wait_text, reply_markup=wait_kb, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=user_id, text=wait_text, reply_markup=wait_kb, parse_mode="HTML")
        except Exception:
            pass

        try:
            await bot.send_message(
                chat_id=partner_id,
                text=(
                    f"🔔 <b>Meslektaşınız Anlaşmayı Onayladı! (#{listing_id})</b>\n\n"
                    f"İletişimde olduğunuz meslektaşınız <b>[🤝 Anlaştık]</b> bildiriminde bulundu.\n\n"
                    f"Anlaşma sağlandıysa lütfen siz de onaylayınız. Karşılıklı onay verildiğinde tevkil tamamlanacak ve puanınız eklenecektir:"
                ),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="🤝 Ben de Anlaştım", callback_data=f"agree:{listing_id}"),
                            InlineKeyboardButton(text="❌ Anlaşamadık", callback_data=f"disagree:{listing_id}")
                        ]
                    ]
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("agree:"))
async def handle_agree(callback: CallbackQuery, db: AsyncSession):
    listing_id = int(callback.data.split(":")[1])
    await execute_agree_step(
        bot=callback.bot,
        user_id=callback.from_user.id,
        listing_id=listing_id,
        db=db,
        callback=callback
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

    await callback.answer()
    role_prefix = "creator" if user.id == session.creator_id else "applicant"

    try:
        await callback.message.edit_text(
            f"❌ <b>Anlaşamama Sebebini Belirtiniz:</b>\n\n"
            f"Lütfen meslektaşınızla anlaşamama gerekçenizi seçiniz.\n"
            f"🚨 <b>Önemli Kural:</b> Tarife altı ücret tekliflerinde sistem tarafından <b>DİREKT SİSTEMDEN UZAKLAŞTIRMA</b> yaptırımı uygulanır:",
            reply_markup=get_reason_keyboard(listing_id, role_prefix=role_prefix),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"[Confirmation] disagree edit_text hatası: {e}")


async def get_next_backup_candidate(listing_id: int, current_rank: int, db: AsyncSession):
    """
    Sıradaki adayı (current_rank sonrası) önce Redis'ten, bulunamazsa PostgreSQL Application tablosundan bulur.
    Dönüş: (user_id, score_ms, queue_number)
    """
    try:
        cand = await RedisQueueService.get_next_available_applicant(listing_id, current_rank=current_rank)
        if cand:
            return cand
    except Exception:
        pass

    stmt = (
        select(Application)
        .where(
            Application.listing_id == listing_id,
            Application.status.in_(["WAITING", "QUEUED"]),
            Application.queue_number > current_rank
        )
        .order_by(Application.queue_number.asc())
        .limit(1)
    )
    res = await db.execute(stmt)
    app = res.scalar_one_or_none()
    if app:
        return app.user_id, float(app.score_ms or 0), app.queue_number

    return None


async def advance_to_next_candidate_or_close(
    bot,
    listing: Listing,
    current_candidate_rank: int,
    db: AsyncSession
):
    """
    Önceki aday ile anlaşılamadığında sıradaki yedek adaya teklif götürür;
    eğer başka aday kalmamışsa ilanı anlaşmazlık nedeniyle kapatır.
    """
    listing_id = listing.id
    next_candidate = await get_next_backup_candidate(listing_id, current_rank=current_candidate_rank, db=db)

    if next_candidate:
        next_uid, next_score, new_rank = next_candidate

        cand_stmt = select(User).where(User.id == next_uid)
        cand_res = await db.execute(cand_stmt)
        cand_user = cand_res.scalar_one_or_none()

        cand_name = cand_user.full_name if (cand_user and cand_user.full_name) else f"Kullanıcı {next_uid}"
        cand_mention = f"@{cand_user.username}" if (cand_user and cand_user.username) else f"<a href='tg://user?id={next_uid}'>{cand_name}</a>"

        listing.status = "MATCHED"
        await db.commit()

        # 1. İlan Sahibine bilgi ver
        try:
            await bot.send_message(
                chat_id=listing.creator_id,
                text=(
                    f"ℹ️ <b>Sıradaki Adaya Geçildi (#{listing_id})</b>\n\n"
                    f"Önceki meslektaşımız ile anlaşma sağlanamadığı için sıra <b>{new_rank}. sıradaki adayımız ({cand_name})</b> meslektaşımıza devredilmiştir.\n\n"
                    f"<i>Aday görevi onayladığında görüşme köprüsü derhal kurulacaktır.</i>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[Confirmation] İlan sahibine sıra devir bildirimi hatası: {e}")

        # 2. Sıradaki Adaya DM'den onay mesajı gönder
        try:
            await bot.send_message(
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

        # 3. Ana grupta 2. kişiyi etiketleyerek bildirim yayınla
        if listing.group_id:
            try:
                await bot.send_message(
                    chat_id=listing.group_id,
                    text=(
                        f"📢 <b>[SIRA SİZE GELDİ — İlan #{listing_id}]</b>\n\n"
                        f"🔔 Sayın {cand_mention}:\n"
                        f"Önceki meslektaşımız ile anlaşma sağlanamadığından <b>{new_rank}. sıradaki aday olarak görüşme hakkı size geçmiştir!</b>\n\n"
                        f"Lütfen görevi onaylamak için bot DM kutunuzu kontrol ediniz."
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"[Confirmation] Gruba sıradaki aday etiket bildirimi gönderilemedi: {e}")

    else:
        # Yedek aday yok -> İlanı anlaşmazlık nedeniyle kapat
        listing.status = "CLOSED_DISAGREED"
        await db.commit()

        try:
            await bot.send_message(
                chat_id=listing.creator_id,
                text=f"ℹ️ #{listing_id} numaralı ilanınız için görüşme sonlandırıldı ve yedek sırada başka aday bulunmadığından ilan kapatıldı."
            )
        except Exception:
            pass

        if listing.group_id:
            try:
                await bot.send_message(
                    chat_id=listing.group_id,
                    text=(
                        f"❌ <b>İLAN KAPATILDI (#{listing_id})</b>\n\n"
                        f"Adaylar ile anlaşma sağlanamadığı ve yedek sırada başka başvuru bulunmadığı için ilan kapatılmıştır."
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await update_group_listing_board(bot, listing, db=db)


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

    await callback.answer()

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
        
        # Kişiyi sistemden uzaklaştır ve 30 ceza puanı ekle
        u_stmt = select(User).where(User.id == violator_id)
        u_res = await db.execute(u_stmt)
        violator = u_res.scalar_one_or_none()
        if violator:
            violator.is_banned = True
            violator.banned_until = ban_until
            violator.ban_reason = f"Tarife altı ücret teklifi / kural ihlali ({ban_days} gün uzaklaştırma)"
            violator.penalty_points += 30

            penalty_log = PenaltyLog(
                user_id=violator_id,
                points=30,
                reason="Tarife altı ücret teklifi / kural ihlali",
                issued_by="SYSTEM_TARIFF_RULE"
            )
            db.add(penalty_log)

        await db.commit()

        # Uzaklaştırılan tarafa bildirim gönder
        try:
            await callback.bot.send_message(
                chat_id=violator_id,
                text=(
                    f"🚨 <b>DİREKT SİSTEMDEN UZAKLAŞTIRILDINIZ (TARİFE ALTI TEKLİF)</b>\n\n"
                    f"#{listing_id} numaralı tevkil görüşmesinde <b>Baro Asgari Ücret Tarifesi / Grup Tarifesi Altında</b> "
                    f"teklifte bulunulduğu tespit edilmiş/raporlanmıştır.\n\n"
                    f"📌 <b>Uygulanan Yaptırımlar:</b>\n"
                    f"• Hesabınız <b>{ban_days} gün</b> boyunca sistemden uzaklaştırılmıştır.\n"
                    f"• Hesabınıza <b>+30 Ceza Puanı</b> eklenmiştir.\n"
                    f"• Kısıtlama Bitiş Tarihi: {format_date_short_tr(ban_until)}\n\n"
                    f"<i>Meslek onuruna ve baro asgari ücret tarifelerine uyulması zorunludur.</i>"
                ),
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"[Confirmation] Tarife uzaklaştırma bildirimi iletilemedi: {e}")

        # Grupta Ceza ve Disiplin Duyurusu Yap
        target_group_id = session.group_id
        if not target_group_id:
            l_stmt = select(Listing.group_id).where(Listing.id == listing_id)
            target_group_id = (await db.execute(l_stmt)).scalar()

        if target_group_id:
            violator_name = violator.full_name or f"{violator_title} Meslektaşımız"
            violator_mention = f"@{violator.username}" if violator.username else violator_name
            grp_alert = (
                f"🚨 <b>DİSİPLİN VE CEZA DUYURUSU</b> 🚨\n\n"
                f"📋 <b>İlgili İlan:</b> #{listing_id}\n"
                f"👤 <b>Uygulanan Kişi:</b> {violator_title} ({violator_mention})\n"
                f"⚖️ <b>Gerekçe:</b> <b>Tarife Altı Ücret Teklifi / Kural İhlali</b>\n"
                f"⚠️ <b>Uygulanan Ceza:</b> <b>+30 Ceza Puanı</b> ve <b>{ban_days} Gün Sistemden Uzaklaştırma</b>\n\n"
                f"<i>Tevkil platformumuzda meslek onuruna ve baro asgari ücret tarifelerine uyulması zorunludur. Denetimler aralıksız sürdürülmektedir.</i>"
            )
            try:
                await callback.bot.send_message(chat_id=target_group_id, text=grp_alert, parse_mode="HTML")
            except Exception as e:
                print(f"[Confirmation] Grupta tarife ceza duyurusu hatası: {e}")

        # Bildiren tarafa onay
        await callback.message.edit_text(
            f"🚨 <b>Tarife İhlali Kaydedildi ve Yaptırım Uygulandı</b>\n\n"
            f"Tarife altı teklif bildirimi nedeniyle karşı taraf <b>{ban_days} gün süreyle doğrudan sistemden uzaklaştırılmış</b> "
            f"ve durum Admin Denetim Grubu'na yüksek öncelikle iletilmiştir.",
            parse_mode="HTML"
        )
        try:
            await callback.bot.send_message(
                chat_id=reporter_id,
                text="ℹ️ <i>Görüşme sonlandırıldı.</i>",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
        except Exception:
            pass

        # Admin Denetim Grubuna Yüksek Öncelikli Alarm
        admin_alert = (
            f"🚨🚨 <b>[TARİFE ALTI ÜCRET İHLALİ — DİREKT UZAKLAŞTIRMA UYGULANDI]</b>\n"
            f"📋 <b>İlan ID:</b> #{listing_id}\n"
            f"👤 <b>Şikayet Eden ({reporter_title}):</b> <code>{reporter_id}</code>\n"
            f"👤 <b>Uzaklaştırılan ({violator_title}):</b> <code>{violator_id}</code>\n"
            f"⚖️ <b>Uygulanan Ceza:</b> {ban_days} Gün Direkt Uzaklaştırma & +30 Ceza Puanı\n"
            f"⏰ <b>Bitiş Tarihi:</b> {format_date_short_tr(ban_until)}\n\n"
            f"<i>Yöneticilerimiz sohbet arşivini yukarıdaki loglardan denetleyebilir.</i>"
        )
        await AuditService.notify_admin_event(callback.bot, admin_alert, listing_id=listing_id)

    else:
        await db.commit()
        await callback.message.edit_text(
            f"❌ <b>Görüşme Kapatıldı</b>\n\n"
            f"Gerekçe: <b>{reason_text}</b> olarak kaydedildi ve admin denetimine iletildi.",
            parse_mode="HTML"
        )
        try:
            await callback.bot.send_message(
                chat_id=callback.from_user.id,
                text="ℹ️ <i>Görüşme sonlandırıldı.</i>",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
        except Exception:
            pass

        # Karşı tarafa bilgi ver
        partner_id = session.applicant_id if callback.from_user.id == session.creator_id else session.creator_id
        try:
            await callback.bot.send_message(
                chat_id=partner_id,
                text=(
                    f"ℹ️ <b>Görüşme Sonlandırıldı</b>\n\n"
                    f"#{listing_id} numaralı tevkil ilanı için görüşme meslektaşınız tarafından ({reason_text}) gerekçesiyle kapatılmıştır."
                ),
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML"
            )
        except Exception:
            pass

        # Admin Denetim Grubuna Detaylı Bilgi
        admin_alert = (
            f"⚠️ <b>[ANLAŞMAZLIK BİLDİRİMİ — İlan #{listing_id}]</b>\n"
            f"📋 <b>İlan ID:</b> #{listing_id}\n"
            f"👤 <b>İlan Sahibi:</b> <code>{session.creator_id}</code> (Onay: {'✅ Onayladı' if session.creator_agreed else '❌ Onaylamadı'})\n"
            f"👤 <b>Başvuran ({current_candidate_rank}. Sıra Aday):</b> <code>{session.applicant_id}</code> (Onay: {'✅ Onayladı' if session.applicant_agreed else '❌ Onaylamadı'})\n"
            f"📌 <b>Anlaşmazlık Bildiren:</b> {reporter_title} (ID: <code>{callback.from_user.id}</code>)\n"
            f"📝 <b>Bildirilen Gerekçe:</b> <b>{reason_text}</b>\n\n"
            f"👇 <i>Aşağıdaki hızlı işlem butonlarını kullanarak müdahale edebilirsiniz:</i>"
        )
        await AuditService.notify_admin_event(
            callback.bot,
            admin_alert,
            reply_markup=get_disagreement_admin_keyboard(session.creator_id, session.applicant_id, listing_id=listing_id),
            listing_id=listing_id
        )

    # İlanı veritabanından çek ve sıradaki yedek adaya geç
    l_stmt = select(Listing).where(Listing.id == listing_id)
    l_res = await db.execute(l_stmt)
    listing = l_res.scalar_one_or_none()

    if listing:
        await advance_to_next_candidate_or_close(
            bot=callback.bot,
            listing=listing,
            current_candidate_rank=current_candidate_rank,
            db=db
        )


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

    await callback.answer()

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

        # Zincirleme devir: Sıradaki bir sonraki adaya git (target_rank + 1)
        await advance_to_next_candidate_or_close(
            bot=callback.bot,
            listing=listing,
            current_candidate_rank=target_rank,
            db=db
        )
