from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.database.models import User, Listing, Application
from bot.services.redis_queue import RedisQueueService
from bot.services.bridge_service import BridgeService
from bot.handlers.group_detector import build_apply_keyboard

router = Router()


async def update_group_listing_board(bot, listing: Listing):
    """
    Gruptaki mesajı tüm başvuranların ad-soyad ve milisaniyeli saat bilgileriyle günceller.
    """
    applicants = await RedisQueueService.get_all_applicants(listing.id)
    if not applicants:
        return

    creator_name = listing.creator.full_name if listing.creator else "İlan Sahibi"
    lines = []
    for app in applicants:
        rank = app["rank"]
        full_name = app["full_name"]
        score_ms = app["score_ms"]
        
        # Milisaniye hassasiyetli saat formatı: HH:MM:SS.mmm
        time_str = datetime.fromtimestamp(score_ms / 1000.0).strftime("%H:%M:%S.%f")[:-3]
        
        status_tag = "🟢 <i>Görüşmede</i>" if rank == 1 else f"⏳ <i>{rank}. Sırada (Yedek)</i>"
        lines.append(f"<b>{rank}.</b> {full_name} — <code>{time_str}</code> [{status_tag}]")

    board_content = "\n".join(lines)
    updated_text = (
        f"📌 <b>Tevkil İlanı (#{listing.id})</b>\n"
        f"👤 <b>İlan Sahibi:</b> {creator_name}\n"
        f"🕒 <b>İlan Saati:</b> <code>{listing.created_at.strftime('%H:%M:%S')}</code>\n\n"
        f"📋 <b>Canlı Başvuru Sıralaması ({len(applicants)} Başvuru):</b>\n"
        f"{board_content}\n\n"
        f"👇 <i>Yedek sıraya girmek için aşağıdaki butonu kullanabilirsiniz:</i>"
    )

    try:
        if listing.bot_reply_message_id:
            await bot.edit_message_text(
                chat_id=listing.group_id,
                message_id=listing.bot_reply_message_id,
                text=updated_text,
                reply_markup=build_apply_keyboard(listing.id),
                parse_mode="HTML"
            )
    except Exception as e:
        # Telegram MessageNotModified veya rate-limit durumları
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
        db_user = User(id=user.id, username=user.username, full_name=user.full_name or "")
        db.add(db_user)
        await db.commit()
    else:
        db_user.username = user.username
        db_user.full_name = user.full_name or db_user.full_name
        await db.commit()

    if db_user.is_banned:
        await callback.answer("⛔ Hesabınız geçici olarak kısıtlı olduğundan başvuramazsınız.", show_alert=True)
        return

    # 3. Redis Milisaniye Sıralamasına Ekle
    user_data = {
        "full_name": user.full_name or f"Av. {user.first_name}",
        "username": user.username,
        "id": user.id
    }
    is_new, rank, score_ms = await RedisQueueService.add_applicant(
        listing_id=listing_id,
        user_id=user.id,
        user_data=user_data
    )

    if not is_new:
        await callback.answer(f"ℹ️ Bu ilana zaten daha önce başvurdunuz. Sıranız: {rank}", show_alert=True)
        return

    # 4. DB Application kaydı oluştur
    app_record = Application(
        listing_id=listing_id,
        user_id=user.id,
        queue_number=rank,
        applied_at=datetime.utcnow(),
        status="ACTIVE" if rank == 1 else "WAITING"
    )
    db.add(app_record)
    await db.commit()

    # 5. Sıralama Algoritması Mantığı
    if rank == 1:
        # Sadece ilk tıklayan kişi görüşme başlatma hakkı kazanır
        await callback.answer("🎉 Tebrikler! 1. sıradasınız. Bot özel mesajından görüşme başlatılıyor...", show_alert=True)
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
        await callback.answer(f"Tevkil için {rank}. sıradasınız.", show_alert=True)
        try:
            await callback.bot.send_message(
                chat_id=user.id,
                text=(
                    f"ℹ️ <b>Tevkil Başvurusu Alındı (İlan #{listing_id})</b>\n\n"
                    f"Tevkil için <b>{rank}. sırasınız</b>.\n"
                    f"1. sıradaki meslektaşımız ile anlaşma sağlanamazsa sıra otomatik olarak size devredilecektir."
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass  # Kullanıcı botu henüz başlatmamış olabilir

    # 6. Gruptaki Şeffaf Panoyu Güncelle
    await update_group_listing_board(callback.bot, listing)
