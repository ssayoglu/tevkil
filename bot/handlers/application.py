import time
from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.database.models import User, Listing, Application
from bot.database.connection import AsyncSessionLocal
from bot.services.redis_queue import RedisQueueService
from bot.services.bridge_service import BridgeService
from bot.services.rank_service import RankService
from bot.handlers.group_detector import build_apply_keyboard
from bot.utils.time_utils import format_timestamp_ms

router = Router()


async def update_group_listing_board(bot, listing: Listing, db: AsyncSession = None):
    """
    Gruptaki mesajı tüm başvuranların ad-soyad, rank puanı, milisaniyeli saat bilgileri
    ve anlık durumlarıyla günceller. İlan sahibinin Telegram hesabı anonim tutulur.
    """
    applicants = await RedisQueueService.get_all_applicants(listing.id)
    if not applicants:
        return

    # DB'deki başvuru durumlarını ve ilan sahibinin rank puanını çek
    status_map = {}
    creator_net_score = 100
    if db is None:
        async with AsyncSessionLocal() as session:
            stmt = select(Application).where(Application.listing_id == listing.id)
            res = await session.execute(stmt)
            for app in res.scalars().all():
                status_map[app.user_id] = app.status

            c_stmt = select(User).where(User.id == listing.creator_id)
            c_res = await session.execute(c_stmt)
            creator = c_res.scalar_one_or_none()
            if creator:
                creator_net_score = RankService.calculate_net_score(creator.rank_score, creator.penalty_points)
    else:
        stmt = select(Application).where(Application.listing_id == listing.id)
        res = await db.execute(stmt)
        for app in res.scalars().all():
            status_map[app.user_id] = app.status

        c_stmt = select(User).where(User.id == listing.creator_id)
        c_res = await db.execute(c_stmt)
        creator = c_res.scalar_one_or_none()
        if creator:
            creator_net_score = RankService.calculate_net_score(creator.rank_score, creator.penalty_points)

    lines = []
    for app in applicants:
        rank = app["rank"]
        full_name = app["full_name"]
        score_ms = app["score_ms"]
        uid = app["user_id"]
        rank_score = app.get("rank_score", 100)
        handicap_lvl = app.get("handicap_level", 0)
        
        # Milisaniye saat gösterimi
        time_str = format_timestamp_ms(score_ms)
        
        # Kullanıcının anlık durumu
        app_status = status_map.get(uid, "WAITING" if rank > 1 else "ACTIVE")
        
        if app_status == "ACTIVE":
            status_tag = "🟢 <i>Görüşmede</i>"
        elif app_status == "ACCEPTED":
            status_tag = "🤝 <i>Anlaşıldı</i>"
        elif app_status == "REJECTED":
            status_tag = "❌ <i>Anlaşılamadı</i>"
        elif app_status == "PASSED":
            status_tag = "🚫 <i>Reddetti</i>"
        else:
            status_tag = f"⏳ <i>{rank}. Sırada (Yedek)</i>"

        handicap_tag = f" (⚠️ -{handicap_lvl} Sıra)" if handicap_lvl > 0 else ""
        lines.append(f"<b>{rank}.</b> {full_name} — ⭐ {rank_score} P.{handicap_tag} — <code>{time_str}</code> [{status_tag}]")

    board_content = "\n".join(lines)
    
    # Genel ilan durum başlığı
    if listing.status == "COMPLETED":
        footer = "✅ <b>İLAN TAMAMLANDI (Anlaşma Sağlandı)</b>"
    elif listing.status == "CLOSED_DISAGREED":
        footer = "❌ <b>İLAN ANLAŞMA SAĞLANAMADIĞI İÇİN KAPATILDI</b>"
    elif listing.status == "CANCELLED_TIMEOUT":
        footer = "⚠️ <b>İLAN İPTAL EDİLDİ (30 Dk Kuralı İhlali)</b>"
    elif listing.status == "CANCELLED_ADMIN":
        footer = "🛑 <b>İLAN YÖNETİCİ TARAFINDAN DURDURULDU</b>"
    else:
        footer = (
            "🚨 <b>ÖNEMLİ KURAL:</b> İlan sahibine özelden yazmak veya tarife altı teklif vermek <b>DİREKT SİSTEMDEN UZAKLAŞTIRMA</b> sebebidir!\n\n"
            "👇 <i>Yedek sıraya girmek için aşağıdaki butonu kullanabilirsiniz:</i>"
        )

    updated_text = (
        f"📌 <b>Tevkil İlanı (#{listing.id})</b>\n"
        f"👤 <b>İlan Sahibi:</b> Meslektaşımız (⭐ {creator_net_score} Puan)\n"
        f"🕒 <b>İlan Saati:</b> <code>{listing.created_at.strftime('%H:%M:%S')}</code>\n\n"
        f"📋 <b>Canlı Başvuru Sıralaması ({len(applicants)} Başvuru):</b>\n"
        f"{board_content}\n\n"
        f"{footer}"
    )

    try:
        if listing.bot_reply_message_id:
            reply_markup = build_apply_keyboard(listing.id) if listing.status in ["OPEN", "MATCHED"] else None
            await bot.edit_message_text(
                chat_id=listing.group_id,
                message_id=listing.bot_reply_message_id,
                text=updated_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
    except Exception as e:
        print(f"[Application] Grup panosu güncelleme uyarısı: {e}")


@router.callback_query(F.data.startswith("apply:"))
async def handle_application(callback: CallbackQuery, db: AsyncSession):
    listing_id = int(callback.data.split(":")[1])
    user = callback.from_user

    # 1. İlanı veritabanından çek
    stmt = (
        select(Listing)
        .where(Listing.id == listing_id)
    )
    res = await db.execute(stmt)
    listing = res.scalar_one_or_none()

    if not listing:
        await callback.answer("❌ İlan bulunamadı.", show_alert=True)
        return

    if listing.status not in ["OPEN", "MATCHED"]:
        await callback.answer("⚠️ Bu ilan tamamlanmış veya iptal edilmiştir.", show_alert=True)
        return

    # İlan sahibinin kendi ilanına başvurmasını engelle
    if listing.creator_id == user.id:
        await callback.answer("⚠️ Kendi tevkil ilanınıza başvuramazsınız.", show_alert=True)
        return

    # 2. Kullanıcıyı DB'ye kaydet/güncelle
    u_stmt = select(User).where(User.id == user.id)
    u_res = await db.execute(u_stmt)
    db_user = u_res.scalar_one_or_none()
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
        await db.refresh(db_user)
    else:
        db_user.username = user.username
        db_user.full_name = user.full_name or db_user.full_name
        await db.commit()

    if db_user.is_banned:
        await callback.answer("⛔ Hesabınız geçici olarak kısıtlı olduğundan başvuramazsınız.", show_alert=True)
        return

    # 3. Rank Puanı ve Handikap Hesaplaması
    base_ms = time.time() * 1000.0
    effective_score_ms, net_score, handicap_lvl = await RankService.calculate_application_score(
        base_ms=base_ms,
        user=db_user,
        db=db
    )

    # 4. Redis Milisaniye Sıralamasına Ekle
    user_data = {
        "full_name": user.full_name or f"Av. {user.first_name}",
        "username": user.username,
        "id": user.id,
        "rank_score": net_score,
        "penalty_points": db_user.penalty_points,
        "handicap_level": handicap_lvl,
        "is_baro_verified": db_user.is_baro_verified
    }
    is_new, rank, score_ms = await RedisQueueService.add_applicant(
        listing_id=listing_id,
        user_id=user.id,
        user_data=user_data,
        custom_score_ms=effective_score_ms
    )

    if not is_new:
        await callback.answer(f"ℹ️ Bu ilana zaten daha önce başvurdunuz. Sıranız: {rank}", show_alert=True)
        return

    # 5. DB Application kaydı oluştur
    app_record = Application(
        listing_id=listing_id,
        user_id=user.id,
        queue_number=rank,
        applied_at=datetime.utcnow(),
        score_ms=score_ms,
        user_rank_score=net_score,
        handicap_level=handicap_lvl,
        status="ACTIVE" if rank == 1 else "WAITING"
    )
    db.add(app_record)
    await db.commit()

    # 6. Sıralama Algoritması Mantığı
    handicap_msg = f"\n⚠️ <i>(Puan durumunuz gereği {handicap_lvl} kademe sıra handikapı uygulandı.)</i>" if handicap_lvl > 0 else ""

    if rank == 1:
        # Sadece ilk tıklayan kişi görüşme başlatma hakkı kazanır
        await callback.answer(f"🎉 Tebrikler! 1. sıradasınız. Bot DM üzerinden görüşme başlatılıyor...{handicap_msg}", show_alert=True)
        await BridgeService.initiate_bridge(
            bot=callback.bot,
            listing_id=listing_id,
            creator_id=listing.creator_id,
            applicant_id=user.id,
            group_id=listing.group_id,
            candidate_rank=1
        )
    else:
        # Diğer Adaylara: "Tevkil için X. sırasınız."
        await callback.answer(f"Tevkil için {rank}. sıradasınız.{handicap_msg}", show_alert=True)
        try:
            await callback.bot.send_message(
                chat_id=user.id,
                text=(
                    f"ℹ️ <b>Tevkil Başvurusu Alındı (İlan #{listing_id})</b>\n\n"
                    f"Tevkil için <b>{rank}. sırasınız</b>. (⭐ Puanınız: {net_score}){handicap_msg}\n\n"
                    f"Önceki meslektaşlarımız ile anlaşma sağlanamazsa sıra otomatik olarak size devredilecektir."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass  # Kullanıcı botu henüz başlatmamış olabilir

    # 7. Gruptaki Şeffaf Panoyu Güncelle
    await update_group_listing_board(callback.bot, listing, db=db)
