from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from bot.config import settings
from bot.database.models import User, Listing, BridgeSession, Application, MessageLog, PenaltyLog
from bot.services.redis_queue import RedisQueueService
from bot.services.audit_service import AuditService
from bot.services.rank_service import RankService
from bot.utils.time_utils import format_datetime_tr, format_date_short_tr

router = Router()


def is_admin_chat(message: Message) -> bool:
    """Mesajın tanımlı Admin Denetim Grubu'ndan gelip gelmediğini kontrol eder."""
    return message.chat.id == settings.admin_chat_id


@router.message(Command("admin_yardim", "admin_help"))
async def cmd_admin_help(message: Message):
    if not is_admin_chat(message):
        return

    text = (
        "🛠️ <b>ADMİN DENETİM PANELİ KOMUTLARI</b>\n\n"
        "• <code>/durdur &lt;ilan_id&gt;</code>\n"
        "  Devam eden bir köprü görüşmesini anında keser ve oturumu kapatır.\n\n"
        "• <code>/kullanici_kisitla &lt;user_id&gt; [gün] [sebep]</code>\n"
        "  Kullanıcıyı belirtilen gün boyunca sistemden yasaklar.\n\n"
        "• <code>/tarife_ban &lt;user_id&gt; [gün] [sebep]</code>\n"
        "  Tarife altı teklif veren kullanıcıya doğrudan ağır ban (varsayılan: 15 gün) ve 30 ceza puanı uygular.\n\n"
        "• <code>/ceza_kaldir &lt;user_id&gt;</code>\n"
        "  Kullanıcının kısıtlamasını derhal kaldırır.\n\n"
        "• <code>/ceza_puani_ver &lt;user_id&gt; &lt;puan&gt; [sebep]</code>\n"
        "  Kullanıcıya ceza puanı işler (sıra handikapını artırır).\n\n"
        "• <code>/puan_ekle &lt;user_id&gt; &lt;puan&gt;</code>\n"
        "  Kullanıcının rank puanını artırır.\n\n"
        "• <code>/kullanici_bilgi &lt;user_id&gt;</code>\n"
        "  Kullanıcının rank, ceza, kısıtlama ve tevkil geçmişini gösterir.\n\n"
        "• <code>/ilan_detay &lt;ilan_id&gt;</code>\n"
        "  İlanın tüm başvuru kuyruğunu ve denetim özetini gösterir.\n\n"
        "• <code>/aktif_ilanlar</code>\n"
        "  Şu anda devam eden tüm köprü oturumlarını listeler.\n\n"
        "• <code>/kara_liste</code>\n"
        "  Aktif kısıtlı (yasaklı) tüm kullanıcıları listeler.\n\n"
        "• <code>/istatistik</code>\n"
        "  Sistem geneli toplam ve günlük tevkil istatistiklerini raporlar."
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


@router.message(Command("tarife_uzaklastir", "tarife_ban"))
async def cmd_tariff_ban(message: Message, db: AsyncSession):
    """Tarife altı teklif veren kullanıcıya doğrudan ağır uzaklaştırma uygular."""
    if not is_admin_chat(message):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        await message.reply("⚠️ Kullanım: <code>/tarife_uzaklastir &lt;user_id&gt; [gün] [sebep]</code>", parse_mode="HTML")
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.reply("❌ Geçersiz kullanıcı ID.")
        return

    days = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else settings.tariff_ban_duration_days
    reason = parts[3] if len(parts) >= 4 else "Tarife altı ücret teklifi / meslek kuralı ihlali"

    ban_until = datetime.utcnow() + timedelta(days=days)

    u_stmt = select(User).where(User.id == user_id)
    res = await db.execute(u_stmt)
    user = res.scalar_one_or_none()

    if not user:
        user = User(id=user_id, is_banned=True, banned_until=ban_until, ban_reason=reason, penalty_points=30)
        db.add(user)
    else:
        user.is_banned = True
        user.banned_until = ban_until
        user.ban_reason = reason
        user.penalty_points += 30

    penalty_log = PenaltyLog(
        user_id=user_id,
        points=30,
        reason=reason,
        issued_by=f"ADMIN_TARIFF_{message.from_user.id}"
    )
    db.add(penalty_log)
    await db.commit()

    # Varsa aktif köprüyü temizle
    await RedisQueueService.remove_active_bridge(user_id)

    # Kullanıcıya tebligat gönder
    try:
        await message.bot.send_message(
            chat_id=user_id,
            text=(
                f"🚨 <b>DİREKT SİSTEMDEN UZAKLAŞTIRILDINIZ (TARİFE ALTI TEKLİF)</b>\n\n"
                f"Baro Asgari Ücret Tarifesi / Grup Tarifesi altında teklifte bulunduğunuz gerekçesiyle "
                f"hesabınız yöneticiler tarafından <b>{days} gün</b> süreyle sistemden uzaklaştırılmış ve <b>+30 Ceza Puanı</b> uygulanmıştır.\n\n"
                f"<b>Gerekçe:</b> {reason}\n"
                f"<b>Kısıtlama Bitiş:</b> {format_date_short_tr(ban_until)}"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await message.reply(
        f"🚨 <code>{user_id}</code> kullanıcısına <b>Tarife Altı Teklif İhlali</b> sebebiyle "
        f"<b>{days} gün DİREKT UZAKLAŞTIRMA</b> ve <b>+30 Ceza Puanı</b> uygulandı.\n"
        f"Bitiş Tarihi: {format_date_short_tr(ban_until)}",
        parse_mode="HTML"
    )


@router.message(Command("kullanici_uzaklastir", "kullanici_kisitla"))
async def cmd_ban_user(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 2:
        await message.reply("⚠️ Kullanım: <code>/kullanici_uzaklastir &lt;user_id&gt; [gün] [sebep]</code>", parse_mode="HTML")
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.reply("❌ Geçersiz kullanıcı ID.")
        return

    days = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else settings.ban_duration_days
    reason = parts[3] if len(parts) >= 4 else "Yönetici kararı ile uzaklaştırıldı"

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
                f"Hesabınız yöneticiler tarafından <b>{days} gün</b> süreyle sistemden uzaklaştırılmıştır.\n"
                f"<b>Sebep:</b> {reason}"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await message.reply(
        f"🔒 <code>{user_id}</code> ID'li kullanıcı <b>{days} gün</b> boyunca sistemden uzaklaştırıldı.\n"
        f"Bitiş Tarihi: {format_date_short_tr(ban_until)}",
        parse_mode="HTML"
    )


@router.message(Command("uzaklastirma_kaldir", "ceza_kaldir"))
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


@router.message(Command("ceza_puani_ver"))
async def cmd_add_penalty_points(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.reply("⚠️ Kullanım: <code>/ceza_puani_ver &lt;user_id&gt; &lt;puan&gt; [sebep]</code>", parse_mode="HTML")
        return

    try:
        user_id = int(parts[1])
        points = int(parts[2])
    except ValueError:
        await message.reply("❌ Geçersiz ID veya puan formatı.")
        return

    reason = parts[3] if len(parts) >= 4 else "Yönetici tarafından ceza puanı uygulandı"
    admin_tag = f"ADMIN_{message.from_user.id}"

    user = await RankService.apply_penalty(
        user_id=user_id,
        points=points,
        reason=reason,
        issued_by=admin_tag,
        db=db
    )

    net_score = RankService.calculate_net_score(user.rank_score, user.penalty_points)

    try:
        await message.bot.send_message(
            chat_id=user_id,
            text=(
                f"⚠️ <b>Hesabınıza Ceza Puanı Eklendi</b>\n\n"
                f"• Eklenen Ceza: <b>+{points} Puan</b>\n"
                f"• Gerekçe: <i>{reason}</i>\n"
                f"• Yeni Net Rank Puanınız: ⭐ <b>{net_score}</b>\n\n"
                f"<i>(Ceza puanları başvuru sıralamanıza kademeli gecikme handikapı getirebilir.)</i>"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await message.reply(
        f"⚠️ <code>{user_id}</code> kullanıcısına <b>+{points} Ceza Puanı</b> uygulandı.\n"
        f"Kullanıcının Yeni Net Puanı: ⭐ <b>{net_score}</b>",
        parse_mode="HTML"
    )


@router.message(Command("puan_ekle"))
async def cmd_add_rank_points(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    parts = message.text.split()
    if len(parts) < 3:
        await message.reply("⚠️ Kullanım: <code>/puan_ekle &lt;user_id&gt; &lt;puan&gt;</code>", parse_mode="HTML")
        return

    try:
        user_id = int(parts[1])
        points = int(parts[2])
    except ValueError:
        await message.reply("❌ Geçersiz ID veya puan formatı.")
        return

    u_stmt = select(User).where(User.id == user_id)
    res = await db.execute(u_stmt)
    user = res.scalar_one_or_none()

    if not user:
        user = User(id=user_id, rank_score=100 + points)
        db.add(user)
    else:
        user.rank_score += points

    await db.commit()
    net = RankService.calculate_net_score(user.rank_score, user.penalty_points)
    await message.reply(f"⭐ <code>{user_id}</code> kullanıcısına <b>+{points} Rank Puanı</b> eklendi. (Net: {net})", parse_mode="HTML")


@router.message(Command("kullanici_bilgi"))
async def cmd_user_info(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Kullanım: <code>/kullanici_bilgi &lt;user_id&gt;</code>", parse_mode="HTML")
        return

    try:
        user_id = int(args[1])
    except ValueError:
        await message.reply("❌ Geçersiz kullanıcı ID.")
        return

    u_stmt = select(User).where(User.id == user_id)
    res = await db.execute(u_stmt)
    user = res.scalar_one_or_none()

    if not user:
        await message.reply("❌ Veritabanında bu ID'ye ait kullanıcı bulunamadı.")
        return

    net_score = RankService.calculate_net_score(user.rank_score, user.penalty_points)
    avg_score = await RankService.get_system_average_score(db)
    handicap = RankService.determine_handicap_level(net_score, avg_score, user.penalty_points)

    ban_info = f"⛔ Kısıtlı ({format_date_short_tr(user.banned_until)} - {user.ban_reason})" if user.is_banned else "✅ Aktif"
    baro_info = f"✅ {user.baro_name} ({user.baro_sicil_no})" if user.is_baro_verified else "❌ Doğrulanmadı"

    text = (
        f"👤 <b>KULLANICI BİLGİ KARTI</b>\n\n"
        f"• <b>Ad Soyad:</b> {user.full_name}\n"
        f"• <b>Kullanıcı Adı:</b> @{user.username or 'Yok'}\n"
        f"• <b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"• <b>Kayıt Tarihi:</b> {format_date_short_tr(user.created_at)}\n"
        f"• <b>Hesap Durumu:</b> {ban_info}\n"
        f"• <b>Baro Kaydı:</b> {baro_info}\n\n"
        f"⭐ <b>Rank ve Skor Durumu:</b>\n"
        f"• Rank Puanı: <b>{user.rank_score}</b>\n"
        f"• Ceza Puanı: <b>{user.penalty_points}</b>\n"
        f"• Efektif Net Skor: ⭐ <b>{net_score}</b>\n"
        f"• Kademeli Sıra Handikapı: <b>{f'{handicap} Kademe' if handicap > 0 else 'Yok'}</b>\n\n"
        f"📊 <b>İşlem İstatistikleri:</b>\n"
        f"• Tamamlanan Tevkil: <b>{user.completed_tevkils_count}</b>\n"
        f"• İptal Edilen / Zaman Aşımı: <b>{user.cancelled_tevkils_count}</b>"
    )
    await message.reply(text, parse_mode="HTML")


@router.message(Command("ilan_detay"))
async def cmd_listing_detail(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Kullanım: <code>/ilan_detay &lt;ilan_id&gt;</code>", parse_mode="HTML")
        return

    try:
        listing_id = int(args[1])
    except ValueError:
        await message.reply("❌ Geçersiz İlan ID.")
        return

    l_stmt = select(Listing).where(Listing.id == listing_id)
    res = await db.execute(l_stmt)
    listing = res.scalar_one_or_none()

    if not listing:
        await message.reply("❌ İlan bulunamadı.")
        return

    # Başvuruları çek
    app_stmt = select(Application).where(Application.listing_id == listing_id).order_by(Application.queue_number)
    app_res = await db.execute(app_stmt)
    apps = app_res.scalars().all()

    # Mesaj log sayısını çek
    log_stmt = select(func.count(MessageLog.id)).where(MessageLog.listing_id == listing_id)
    log_count = (await db.execute(log_stmt)).scalar() or 0

    lines = [
        f"📋 <b>İLAN DETAYI (#{listing.id})</b>",
        f"• <b>Durum:</b> <code>{listing.status}</code>",
        f"• <b>Grup:</b> {listing.group_title} (<code>{listing.group_id}</code>)",
        f"• <b>İlan Sahibi ID:</b> <code>{listing.creator_id}</code>",
        f"• <b>Açılış Tarihi:</b> {format_datetime_tr(listing.created_at)}",
        f"• <b>Denetim Log Sayısı:</b> {log_count} Mesaj/Dosya\n",
        f"👥 <b>Başvuru Kuyruğu ({len(apps)} Kişi):</b>"
    ]

    for a in apps:
        lines.append(f"  {a.queue_number}. User ID: <code>{a.user_id}</code> | Durum: <code>{a.status}</code> (⭐ {a.user_rank_score} Puan)")

    lines.append(f"\n📝 <b>İlan Metni:</b>\n<i>{listing.raw_text[:300]}</i>")
    await message.reply("\n".join(lines), parse_mode="HTML")


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
            f"  Aday: <code>{s.applicant_id}</code> ({s.candidate_rank}. Sıra)\n"
            f"  İlk Mesaj Gönderildi mi: {'Evet ✅' if s.creator_first_message_sent else 'Hayır ⏳'}\n"
            f"  Durdurmak için: <code>/durdur {s.listing_id}</code>\n"
        )

    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("kara_liste"))
async def cmd_ban_list(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    now = datetime.utcnow()
    stmt = select(User).where(User.is_banned == True, User.banned_until > now).order_by(User.banned_until.asc())
    res = await db.execute(stmt)
    banned_users = res.scalars().all()

    if not banned_users:
        await message.reply("ℹ️ Şu anda aktif kısıtlı (yasaklı) kullanıcı bulunmamaktadır.")
        return

    lines = [f"🔒 <b>Aktif Kısıtlı Kullanıcılar ({len(banned_users)} Kişi):</b>\n"]
    for u in banned_users:
        lines.append(
            f"• <b>{u.full_name}</b> (<code>{u.id}</code>)\n"
            f"  Bitiş: {format_date_short_tr(u.banned_until)}\n"
            f"  Sebep: <i>{u.ban_reason}</i>\n"
            f"  Cezayı Kaldır: <code>/ceza_kaldir {u.id}</code>\n"
        )
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("istatistik", "stats"))
async def cmd_stats(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_listings = (await db.execute(select(func.count(Listing.id)))).scalar() or 0
    completed_listings = (await db.execute(select(func.count(Listing.id)).where(Listing.status == "COMPLETED"))).scalar() or 0
    timeout_cancelled = (await db.execute(select(func.count(Listing.id)).where(Listing.status == "CANCELLED_TIMEOUT"))).scalar() or 0
    active_sessions = (await db.execute(select(func.count(BridgeSession.id)).where(BridgeSession.is_active == True))).scalar() or 0
    total_logs = (await db.execute(select(func.count(MessageLog.id)))).scalar() or 0
    now = datetime.utcnow()
    banned_count = (await db.execute(select(func.count(User.id)).where(User.is_banned == True, User.banned_until > now))).scalar() or 0
    avg_score = await RankService.get_system_average_score(db)

    text = (
        "📊 <b>TEVKİL BOTU SİSTEM İSTATİSTİKLERİ</b>\n\n"
        f"👥 <b>Kullanıcılar:</b>\n"
        f"• Toplam Kayıtlı Kullanıcı: <b>{total_users}</b>\n"
        f"• Sistem Ortalama Rank Skoru: ⭐ <b>{avg_score:.1f}</b>\n"
        f"• Aktif Kısıtlı Kullanıcı Sayısı: <b>{banned_count}</b>\n\n"
        f"📋 <b>İlanlar ve Süreçler:</b>\n"
        f"• Toplam Açılan İlan: <b>{total_listings}</b>\n"
        f"• Başarıyla Tamamlanan Tevkil: <b>{completed_listings}</b>\n"
        f"• 30 Dk Zaman Aşımıyla İptal: <b>{timeout_cancelled}</b>\n"
        f"• Devam Eden Aktif Görüşme: <b>{active_sessions}</b>\n\n"
        f"🛡️ <b>Denetim Grubu:</b>\n"
        f"• Toplam Arşivlenen Mesaj/Dosya: <b>{total_logs}</b>"
    )
    await message.reply(text, parse_mode="HTML")
