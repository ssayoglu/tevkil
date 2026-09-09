import re
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
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


def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🧹 Tüm Kısıtları Kaldır (Test Modu)", callback_data="adm_act:reset_all:0")
        ],
        [
            InlineKeyboardButton(text="📋 Aktif Görüşmeler", callback_data="adm_act:view_active:0"),
            InlineKeyboardButton(text="🔒 Kara Liste", callback_data="adm_act:view_blacklist:0")
        ],
        [
            InlineKeyboardButton(text="📊 Sistem İstatistikleri", callback_data="adm_act:view_stats:0")
        ]
    ])


async def reset_all_test_restrictions(db: AsyncSession) -> dict:
    """Test süresince tüm kullanıcı yasaklarını, ceza puanlarını ve aktif köprü oturumlarını sıfırlar."""
    banned_count = (await db.execute(select(func.count(User.id)).where(User.is_banned == True))).scalar() or 0
    penalized_count = (await db.execute(select(func.count(User.id)).where(User.penalty_points > 0))).scalar() or 0
    active_sessions_count = (await db.execute(select(func.count(BridgeSession.id)).where(BridgeSession.is_active == True))).scalar() or 0

    await db.execute(
        update(User).values(
            is_banned=False,
            banned_until=None,
            ban_reason=None,
            penalty_points=0,
            rank_score=100
        )
    )

    await db.execute(
        update(BridgeSession).where(BridgeSession.is_active == True).values(
            is_active=False,
            closed_at=datetime.utcnow(),
            close_reason="ADMIN_TEST_RESET"
        )
    )

    await db.commit()
    await RedisQueueService.flush_all_active_bridges()

    return {
        "banned_count": banned_count,
        "penalized_count": penalized_count,
        "active_sessions_count": active_sessions_count
    }


async def get_stats_text(db: AsyncSession) -> str:
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_listings = (await db.execute(select(func.count(Listing.id)))).scalar() or 0
    completed_listings = (await db.execute(select(func.count(Listing.id)).where(Listing.status == "COMPLETED"))).scalar() or 0
    timeout_cancelled = (await db.execute(select(func.count(Listing.id)).where(Listing.status == "CANCELLED_TIMEOUT"))).scalar() or 0
    active_sessions = (await db.execute(select(func.count(BridgeSession.id)).where(BridgeSession.is_active == True))).scalar() or 0
    total_logs = (await db.execute(select(func.count(MessageLog.id)))).scalar() or 0
    now = datetime.utcnow()
    banned_count = (await db.execute(select(func.count(User.id)).where(User.is_banned == True, User.banned_until > now))).scalar() or 0
    avg_score = await RankService.get_system_average_score(db)

    return (
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


async def get_blacklist_text(db: AsyncSession) -> str:
    now = datetime.utcnow()
    stmt = select(User).where(User.is_banned == True, User.banned_until > now).order_by(User.banned_until.asc())
    res = await db.execute(stmt)
    banned_users = res.scalars().all()

    if not banned_users:
        return "ℹ️ Şu anda aktif kısıtlı (yasaklı) kullanıcı bulunmamaktadır."

    lines = [f"🔒 <b>Aktif Kısıtlı Kullanıcılar ({len(banned_users)} Kişi):</b>\n"]
    for u in banned_users:
        lines.append(
            f"• <b>{u.full_name}</b> (<code>{u.id}</code>)\n"
            f"  Bitiş: {format_date_short_tr(u.banned_until)}\n"
            f"  Sebep: <i>{u.ban_reason}</i>\n"
            f"  Cezayı Kaldır: <code>/ceza_kaldir {u.id}</code>\n"
        )
    return "\n".join(lines)


async def get_active_sessions_text(db: AsyncSession) -> str:
    stmt = select(BridgeSession).where(BridgeSession.is_active == True)
    res = await db.execute(stmt)
    sessions = res.scalars().all()

    if not sessions:
        return "ℹ️ Şu anda devam eden aktif bir tevkil görüşmesi bulunmamaktadır."

    lines = ["📋 <b>Devam Eden Aktif Görüşmeler:</b>\n"]
    for s in sessions:
        lines.append(
            f"• <b>İlan #{s.listing_id}</b> | Başlangıç: {s.started_at.strftime('%H:%M:%S')}\n"
            f"  İlan Sahibi: <code>{s.creator_id}</code>\n"
            f"  Aday: <code>{s.applicant_id}</code> ({s.candidate_rank}. Sıra)\n"
            f"  İlk Mesaj Gönderildi mi: {'Evet ✅' if s.creator_first_message_sent else 'Hayır ⏳'}\n"
            f"  Durdurmak için: <code>/durdur {s.listing_id}</code>\n"
        )
    return "\n".join(lines)


def render_test_commands_guide() -> str:
    return (
        "🧪 <b>TEST REHBERİ VE YÖNETİM KOMUTLARI</b>\n\n"
        "🧹 <b>Kısıtları ve Oturumları Sıfırlama:</b>\n"
        "• <code>/sifirla</code> veya <code>/tum_kisitlari_kaldir</code>\n"
        "  <i>Tüm kullanıcıların banlarını, ceza puanlarını sıfırlar, köprü oturumlarını temizler.</i>\n\n"
        "📜 <b>İlan Denetim ve Mesaj Logları:</b>\n"
        "• <code>#12 log</code> veya <code>/log 12</code>\n"
        "  <i>İlanın tüm mesajlaşma geçmişini ve yetki belgelerini döker (3 ay saklanır).</i>\n\n"
        "🕵️ <b>Kullanıcı Dosyası Sorgulama:</b>\n"
        "• <code>@kullanici kimdir</code> veya <code>/kimdir @kullanici</code>\n"
        "  <i>Kullanıcının güven puanını, ceza geçmişini ve baro kaydını gösterir.</i>\n\n"
        "👥 <b>Kuyruk ve İlan Detayı:</b>\n"
        "• <code>/ilan_detay &lt;ilan_id&gt;</code>\n"
        "  <i>Başvuru sırasını, milisaniye skorlarını ve durumunu listeler.</i>\n\n"
        "🛑 <b>Müdahale ve Kısıtlama Komutları:</b>\n"
        "• <code>/durdur &lt;ilan_id&gt;</code> — Görüşmeyi derhal keser.\n"
        "• <code>/kullanici_kisitla &lt;user_id&gt; [gün] [sebep]</code> — Ban uygular.\n"
        "• <code>/tarife_ban &lt;user_id&gt;</code> — Tarife altı teklif cezası (15 gün + 30 puan).\n"
        "• <code>/ceza_kaldir &lt;user_id&gt;</code> — Kısıtlamayı kaldırır.\n"
        "• <code>/ceza_puani_ver &lt;user_id&gt; &lt;puan&gt;</code> — Ceza puanı ekler.\n"
        "• <code>/puan_ekle &lt;user_id&gt; &lt;puan&gt;</code> — Rank puanı ekler.\n\n"
        "📊 <b>Genel Listeler ve Durum:</b>\n"
        "• <code>/aktif_ilanlar</code> — Devam eden görüşmeler.\n"
        "• <code>/kara_liste</code> — Yasaklı kullanıcılar.\n"
        "• <code>/istatistik</code> — Sistem geneli istatistikler."
    )


@router.message(Command("test", "testler", "test_yardim", "test_komutlari", "testrehberi", prefix="/!"))
async def cmd_test_help(message: Message):
    if not is_admin_chat(message):
        return
    text = render_test_commands_guide()
    await message.reply(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")


@router.message(Command("admin_yardim", "admin_help", "yardim", "help", prefix="/!"))
async def cmd_admin_help(message: Message):
    if not is_admin_chat(message):
        return

    text = (
        "🛠️ <b>ADMİN DENETİM PANELİ KOMUTLARI</b>\n\n"
        "• <code>!test</code> veya <code>/test</code>\n"
        "  Test süresince kullanabileceğiniz tüm test ve yönetim komutlarını listeler.\n\n"
        "• <code>#x log</code> veya <code>/log &lt;ilan_id&gt;</code>\n"
        "  İlanın tüm mesaj ve denetim loglarını döker (Loglar 3 ay / 90 gün saklanır).\n\n"
        "• <code>@kullanici kimdir</code> veya <code>/kimdir &lt;user_id&gt;</code>\n"
        "  Kullanıcının kimlik, rank, ceza, baro ve ihlal geçmişini gösterir.\n\n"
        "• <code>/tum_kisitlari_kaldir</code> (veya <code>/sifirla</code>)\n"
        "  Test modunda tüm kullanıcıların kısıtlamalarını ve aktif köprü oturumlarını anında sıfırlar.\n\n"
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
        "• <code>/ilan_detay &lt;ilan_id&gt;</code>\n"
        "  İlanın tüm başvuru kuyruğunu ve denetim özetini gösterir.\n\n"
        "• <code>/aktif_ilanlar</code>\n"
        "  Şu anda devam eden tüm köprü oturumlarını listeler.\n\n"
        "• <code>/kara_liste</code>\n"
        "  Aktif kısıtlı (yasaklı) tüm kullanıcıları listeler.\n\n"
        "• <code>/istatistik</code>\n"
        "  Sistem geneli toplam ve günlük tevkil istatistiklerini raporlar."
    )
    await message.reply(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")


@router.message(Command("tum_kisitlari_kaldir", "sifirla", "test_sifirla", "reset_all"))
async def cmd_reset_all_test_restrictions(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    res = await reset_all_test_restrictions(db)
    summary = (
        "🧹 <b>TEST MODU: TÜM KISITLAR VE OTURUMLAR SIFIRLANDI</b>\n\n"
        f"• <b>Yasağı Kaldırılan Kullanıcı:</b> {res['banned_count']}\n"
        f"• <b>Ceza Puanı Sıfırlanan:</b> {res['penalized_count']}\n"
        f"• <b>Kapatılan Aktif Görüşme:</b> {res['active_sessions_count']}\n"
        "• <b>Redis Köprü Oturumları:</b> Temizlendi ✅\n"
        "• <b>Tüm Kullanıcı Güven Skorları:</b> ⭐ 100 (Varsayılan) yapıldı.\n\n"
        "<i>Tüm test kullanıcıları artık gruplarda serbestçe mesaj atabilir ve yeni ilana başvurabilir.</i>"
    )
    await message.reply(summary, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")


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


async def render_user_profile_dossier(user: User, db: AsyncSession) -> str:
    net_score = RankService.calculate_net_score(user.rank_score, user.penalty_points)
    avg_score = await RankService.get_system_average_score(db)
    handicap = RankService.determine_handicap_level(net_score, avg_score, user.penalty_points)

    # Ceza loglarını çek (en son 5 ceza)
    p_stmt = select(PenaltyLog).where(PenaltyLog.user_id == user.id).order_by(PenaltyLog.id.desc()).limit(5)
    p_res = await db.execute(p_stmt)
    penalty_logs = p_res.scalars().all()

    # İlan ve başvuru istatistikleri
    listing_count_stmt = select(func.count(Listing.id)).where(Listing.creator_id == user.id)
    listing_count = (await db.execute(listing_count_stmt)).scalar() or 0

    app_count_stmt = select(func.count(Application.id)).where(Application.user_id == user.id)
    app_count = (await db.execute(app_count_stmt)).scalar() or 0

    # Kısıtlama durumu
    now = datetime.utcnow()
    if user.is_banned and user.banned_until and user.banned_until > now:
        ban_until_str = format_date_short_tr(user.banned_until)
        ban_status = f"⛔ <b>SİSTEMDEN UZAKLAŞTIRILMIŞ</b>\n  • <b>Kısıtlama Bitiş:</b> {ban_until_str}\n  • <b>Gerekçe:</b> <i>{user.ban_reason or 'Kural ihlali'}</i>"
    else:
        ban_status = "✅ <b>Aktif / Temiz</b> (Kısıtlama Yok)"

    # Baro bilgisi
    if user.is_baro_verified:
        baro_status = f"✅ Doğrulanmış ({user.baro_name} - Sicil: {user.baro_sicil_no})"
    else:
        baro_status = "❌ Henüz Doğrulanmadı"

    # İhlal kayıtları dökümü
    if penalty_logs:
        penalty_lines = []
        for p in penalty_logs:
            p_date = format_date_short_tr(p.created_at)
            penalty_lines.append(f"  • 📅 <code>{p_date}</code> — <b>+{p.points} Ceza Puanı</b>\n    └ <i>Sebep: {p.reason}</i> (Kaynak: <code>{p.issued_by}</code>)")
        penalty_text = "\n".join(penalty_lines)
    else:
        penalty_text = "  <i>(Kayıtlı herhangi bir ceza veya ihlal logu bulunmuyor.)</i>"

    handicap_str = f"⚠️ <b>-{handicap} Sıra Gecikme Cezası</b>" if handicap > 0 else "✅ Handikap Yok (Normal Sıra)"

    return (
        f"🕵️ <b>KULLANICI DENETİM VE İHLAL DOSYASI</b>\n\n"
        f"👤 <b>Kimlik Bilgileri:</b>\n"
        f"• <b>Ad Soyad:</b> {user.full_name or 'Belirtilmemiş'}\n"
        f"• <b>Kullanıcı Adı:</b> @{user.username or 'yok'}\n"
        f"• <b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"• <b>Baro Kaydı:</b> {baro_status}\n"
        f"• <b>Kayıt Tarihi:</b> {format_date_short_tr(user.created_at)}\n\n"
        f"🛡️ <b>Hesap ve Ceza Durumu:</b>\n"
        f"• <b>Durum:</b> {ban_status}\n"
        f"• <b>Net Güven Skoru:</b> ⭐ <b>{net_score}</b> (Rank: {user.rank_score} | Toplam Ceza: {user.penalty_points})\n"
        f"• <b>Sıra Handikapı:</b> {handicap_str}\n\n"
        f"📊 <b>Tevkil İstatistikleri:</b>\n"
        f"• Başarıyla Tamamlanan: <b>{user.completed_tevkils_count}</b>\n"
        f"• İptal Edilen / Kural İhlali: <b>{user.cancelled_tevkils_count}</b>\n"
        f"• Açtığı Toplam İlan: <b>{listing_count}</b> | Başvurduğu İlan: <b>{app_count}</b>\n\n"
        f"🚨 <b>Son İhlal ve Ceza Geçmişi:</b>\n"
        f"{penalty_text}\n\n"
        f"🛠️ <b>Yönetici Hızlı Müdahale Komutları:</b>\n"
        f"• Uzaklaştır: <code>/kullanici_uzaklastir {user.id} 5 Gerekçe</code>\n"
        f"• Ceza Puanı: <code>/ceza_puani_ver {user.id} 10 Gerekçe</code>\n"
        f"• Kısıtlama Kaldır: <code>/uzaklastirma_kaldir {user.id}</code>"
    )


async def get_listing_queue_text(listing_id: int, db: AsyncSession) -> str:
    l_stmt = select(Listing).where(Listing.id == listing_id)
    l_res = await db.execute(l_stmt)
    listing = l_res.scalar_one_or_none()

    if not listing:
        return "❌ İlan bulunamadı."

    app_stmt = select(Application).where(Application.listing_id == listing_id).order_by(Application.queue_number)
    app_res = await db.execute(app_stmt)
    apps = app_res.scalars().all()

    log_stmt = select(func.count(MessageLog.id)).where(MessageLog.listing_id == listing_id)
    log_count = (await db.execute(log_stmt)).scalar() or 0

    lines = [
        f"📋 <b>İLAN DETAYI VE BAŞVURU KUYRUĞU (#{listing.id})</b>",
        f"• <b>Durum:</b> <code>{listing.status}</code>",
        f"• <b>Grup:</b> {listing.group_title or 'Grup'} (<code>{listing.group_id}</code>)",
        f"• <b>İlan Sahibi ID:</b> <code>{listing.creator_id}</code>",
        f"• <b>Açılış Tarihi:</b> {format_datetime_tr(listing.created_at)}",
        f"• <b>Denetim Log Sayısı:</b> {log_count} Mesaj/Dosya (3 Aylık Arşiv)\n",
        f"👥 <b>Başvuru Kuyruğu ({len(apps)} Kişi):</b>"
    ]

    for a in apps:
        lines.append(f"  {a.queue_number}. User ID: <code>{a.user_id}</code> | Durum: <code>{a.status}</code> (⭐ {a.user_rank_score} Puan)")

    lines.append(f"\n📝 <b>İlan Metni:</b>\n<i>{listing.raw_text[:300]}</i>")
    return "\n".join(lines)


async def render_listing_logs_dossier(listing_id: int, db: AsyncSession):
    l_stmt = select(Listing).where(Listing.id == listing_id)
    l_res = await db.execute(l_stmt)
    listing = l_res.scalar_one_or_none()

    if not listing:
        return None, None

    u_stmt = select(User).where(User.id == listing.creator_id)
    creator = (await db.execute(u_stmt)).scalar_one_or_none()
    creator_name = creator.full_name if creator and creator.full_name else f"Kullanıcı {listing.creator_id}"
    creator_uname = f"@{creator.username}" if creator and creator.username else "Yok"

    s_stmt = select(BridgeSession).where(BridgeSession.listing_id == listing_id).order_by(BridgeSession.id.desc())
    s_res = await db.execute(s_stmt)
    session = s_res.scalar_one_or_none()

    applicant_user = None
    if session:
        app_u_stmt = select(User).where(User.id == session.applicant_id)
        applicant_user = (await db.execute(app_u_stmt)).scalar_one_or_none()

    applicant_name = applicant_user.full_name if applicant_user and applicant_user.full_name else (f"Kullanıcı {session.applicant_id}" if session else "Henüz Yok")
    applicant_uname = f"@{applicant_user.username}" if applicant_user and applicant_user.username else "Yok"

    log_stmt = select(MessageLog).where(MessageLog.listing_id == listing_id).order_by(MessageLog.sent_at.asc(), MessageLog.id.asc())
    log_res = await db.execute(log_stmt)
    logs = log_res.scalars().all()

    status_tr_map = {
        "OPEN": "🟢 Açık (Başvuru Bekliyor)",
        "MATCHED": "🟡 Eşleşti (Köprü Görüşmesi Aktif)",
        "COMPLETED": "✅ Tamamlandı (Başarıyla Anlaşıldı)",
        "CANCELLED_TIMEOUT": "⏰ Zaman Aşımı ile İptal (30 Dk Kuralı)",
        "CANCELLED_DISAGREED": "❌ Anlaşılamadı (İptal Edildi)",
        "CLOSED_DISAGREED": "❌ Adaylarla Anlaşılamadı (Kapatıldı)",
        "CANCELLED_ADMIN": "🛑 Yönetici Müdahalesiyle Durduruldu",
        "CANCELLED_USER": "🚫 İlan Sahibi Tarafından İptal Edildi"
    }
    status_text = status_tr_map.get(listing.status, listing.status)

    if session:
        s_status = "🟢 AKTİF GÖRÜŞME" if session.is_active else f"🔴 KAPALI ({session.close_reason or 'Tamamlandı'})"
        first_msg = "Evet ✅" if session.creator_first_message_sent else "Hayır ⏳"
        session_info = (
            f"🤝 <b>Köprü / Görüşme Oturumu:</b>\n"
            f"• <b>Aday:</b> {applicant_name} ({applicant_uname} - ID: <code>{session.applicant_id}</code>)\n"
            f"• <b>Sırası:</b> {session.candidate_rank}. Sıradaki Aday\n"
            f"• <b>İlk Mesaj:</b> {first_msg}\n"
            f"• <b>Oturum Durumu:</b> <code>{s_status}</code>\n"
            f"• <b>Başlangıç:</b> {format_datetime_tr(session.started_at)}\n"
        )
    else:
        session_info = "🤝 <b>Köprü Görüşmesi:</b> <i>(Henüz bir adayla eşleşme oturumu başlamadı.)</i>\n"

    if logs:
        msg_lines = []
        for idx, l in enumerate(logs, 1):
            sent_time = l.sent_at.strftime("%H:%M:%S")
            role_icon = "👤" if "Sahip" in (l.sender_role or "") else ("🙋" if "Aday" in (l.sender_role or "") else "⚙️")

            if l.content_type == "photo":
                content_desc = f"📷 <i>[Fotoğraf]</i> {l.text_content or ''}"
            elif l.content_type == "document":
                content_desc = f"📄 <i>[{l.file_name or 'Doküman'}]</i> {l.text_content or ''}"
            elif l.content_type == "voice":
                content_desc = f"🎤 <i>[Sesli Mesaj]</i>"
            else:
                content_desc = l.text_content or ""

            if len(content_desc) > 200:
                content_desc = content_desc[:197] + "..."

            prefix = "└" if idx == len(logs) else "├"
            msg_lines.append(f"{prefix} 🕒 <code>{sent_time}</code> {role_icon} <b>{l.sender_role}:</b> {content_desc}")

        formatted_logs = "\n".join(msg_lines)
    else:
        formatted_logs = "  <i>(Bu ilana ait arşivlenmiş mesaj kaydı bulunmamaktadır.)</i>"

    dossier_text = (
        f"📜 <b>İLAN #{listing.id} DENETİM VE MESAJ LOGLARI</b>\n"
        f"<i>(Denetim logları 3 ay / 90 gün boyunca saklanır)</i>\n\n"
        f"📋 <b>İlan Bilgileri:</b>\n"
        f"• <b>Durum:</b> {status_text}\n"
        f"• <b>Grup:</b> {listing.group_title or 'Grup'} (<code>{listing.group_id}</code>)\n"
        f"• <b>İlan Sahibi:</b> {creator_name} ({creator_uname} - ID: <code>{listing.creator_id}</code>)\n"
        f"• <b>Açılış Tarihi:</b> {format_datetime_tr(listing.created_at)}\n"
        f"• <b>İlan Metni:</b> <i>{listing.raw_text[:200]}</i>\n\n"
        f"{session_info}\n"
        f"💬 <b>Görüşme Mesaj Geçmişi ({len(logs)} Kayıt):</b>\n"
        f"{formatted_logs}\n\n"
        f"ℹ️ <i>Mesaj logları KVKK ve denetim kuralları gereği 3 ay (90 gün) boyunca güvenli şekilde saklanmaktadır.</i>"
    )

    buttons = []
    user_btns = []
    user_btns.append(InlineKeyboardButton(text="👤 İlan Sahibi", callback_data=f"adm_act:whois:{listing.creator_id}"))
    if session:
        user_btns.append(InlineKeyboardButton(text="👤 Aday", callback_data=f"adm_act:whois:{session.applicant_id}"))
    if user_btns:
        buttons.append(user_btns)

    action_row = []
    if session and session.is_active:
        action_row.append(InlineKeyboardButton(text="🛑 Görüşmeyi Durdur", callback_data=f"adm_act:stop_session:{listing.id}"))
    action_row.append(InlineKeyboardButton(text="👥 Başvuru Kuyruğu", callback_data=f"adm_act:view_queue:{listing.id}"))
    buttons.append(action_row)

    buttons.append([InlineKeyboardButton(text="🧹 Tüm Kısıtları Kaldır", callback_data="adm_act:reset_all:0")])

    return dossier_text, InlineKeyboardMarkup(inline_keyboard=buttons)


def build_user_admin_keyboard(user_id: int, is_banned: bool = False) -> InlineKeyboardMarkup:
    if is_banned:
        buttons = [
            [
                InlineKeyboardButton(text="✅ Kısıtlamayı Kaldır", callback_data=f"adm_act:unban:{user_id}")
            ],
            [
                InlineKeyboardButton(text="⚠️ +10 Ceza Puanı", callback_data=f"adm_act:penalty:{user_id}:10"),
                InlineKeyboardButton(text="⭐ +5 Rank Puanı", callback_data=f"adm_act:rank:{user_id}:5")
            ]
        ]
    else:
        buttons = [
            [
                InlineKeyboardButton(text="⛔ 5 Gün Uzaklaştır", callback_data=f"adm_act:ban:{user_id}:5"),
                InlineKeyboardButton(text="🚨 15 Gün (Tarife Cezası)", callback_data=f"adm_act:ban:{user_id}:15")
            ],
            [
                InlineKeyboardButton(text="⚠️ +10 Ceza Puanı", callback_data=f"adm_act:penalty:{user_id}:10"),
                InlineKeyboardButton(text="⭐ +5 Rank Puanı", callback_data=f"adm_act:rank:{user_id}:5")
            ]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.startswith("adm_act:"))
async def handle_admin_action_callback(callback: CallbackQuery, db: AsyncSession):
    if callback.message.chat.id != settings.admin_chat_id:
        await callback.answer("⚠️ Bu butonlar sadece Admin Grubunda geçerlidir.", show_alert=True)
        return

    parts = callback.data.split(":")
    action = parts[1]
    target_uid = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
    val = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 0

    if action == "reset_all":
        res = await reset_all_test_restrictions(db)
        summary = (
            "🧹 <b>TEST MODU: TÜM KISITLAR VE OTURUMLAR SIFIRLANDI</b>\n\n"
            f"• <b>Yasağı Kaldırılan Kullanıcı:</b> {res['banned_count']}\n"
            f"• <b>Ceza Puanı Sıfırlanan:</b> {res['penalized_count']}\n"
            f"• <b>Kapatılan Aktif Görüşme:</b> {res['active_sessions_count']}\n"
            "• <b>Redis Köprü Oturumları:</b> Temizlendi ✅\n"
            "• <b>Tüm Kullanıcı Güven Skorları:</b> ⭐ 100 (Varsayılan) yapıldı.\n\n"
            "<i>Tüm test kullanıcıları artık gruplarda serbestçe mesaj atabilir ve yeni ilana başvurabilir.</i>"
        )
        await callback.answer("🧹 Tüm kısıtlamalar başarıyla sıfırlandı!", show_alert=True)
        try:
            await callback.message.reply(summary, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")
        except Exception:
            await callback.message.edit_text(summary, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")
        return

    elif action == "view_active":
        await callback.answer()
        text = await get_active_sessions_text(db)
        await callback.message.reply(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")
        return

    elif action == "view_blacklist":
        await callback.answer()
        text = await get_blacklist_text(db)
        await callback.message.reply(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")
        return

    elif action == "view_stats":
        await callback.answer()
        text = await get_stats_text(db)
        await callback.message.reply(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")
        return

    elif action == "stop_session":
        listing_id = target_uid
        s_stmt = select(BridgeSession).where(BridgeSession.listing_id == listing_id, BridgeSession.is_active == True)
        res = await db.execute(s_stmt)
        session = res.scalar_one_or_none()
        if session:
            session.is_active = False
            session.closed_at = datetime.utcnow()
            session.close_reason = "ADMIN_STOPPED"

            l_stmt = select(Listing).where(Listing.id == listing_id)
            l_res = await db.execute(l_stmt)
            listing = l_res.scalar_one_or_none()
            if listing:
                listing.status = "CANCELLED_ADMIN"
                listing.cancellation_reason = "Yönetici müdahalesiyle durduruldu"

            await db.commit()
            await RedisQueueService.remove_active_bridge(session.creator_id)
            await RedisQueueService.remove_active_bridge(session.applicant_id)
            await callback.answer(f"🛑 #{listing_id} görüşmesi durduruldu!", show_alert=True)
        else:
            await callback.answer("ℹ️ Aktif bir görüşme oturumu bulunamadı.", show_alert=True)

        dossier, kb = await render_listing_logs_dossier(listing_id, db)
        if dossier:
            try:
                await callback.message.edit_text(dossier, reply_markup=kb, parse_mode="HTML")
            except Exception:
                pass
        return

    elif action == "view_queue":
        await callback.answer()
        listing_id = target_uid
        queue_text = await get_listing_queue_text(listing_id, db)
        await callback.message.reply(queue_text, parse_mode="HTML")
        return

    u_stmt = select(User).where(User.id == target_uid)
    res = await db.execute(u_stmt)
    user = res.scalar_one_or_none()

    if not user:
        await callback.answer("❌ Kullanıcı bulunamadı.", show_alert=True)
        return

    if action == "whois":
        await callback.answer()
        dossier = await render_user_profile_dossier(user, db)
        kb = build_user_admin_keyboard(user.id, is_banned=user.is_banned)
        await callback.message.reply(dossier, reply_markup=kb, parse_mode="HTML")
        return

    admin_name = callback.from_user.full_name or f"Admin {callback.from_user.id}"

    if action == "ban":
        days = val if val > 0 else 5
        ban_until = datetime.utcnow() + timedelta(days=days)
        user.is_banned = True
        user.banned_until = ban_until
        user.ban_reason = f"Yönetici ({admin_name}) tarafından {days} gün uzaklaştırıldı"
        user.penalty_points += 20

        penalty_log = PenaltyLog(
            user_id=target_uid,
            points=20,
            reason=f"Admin panelinden {days} gün uzaklaştırma",
            issued_by=f"ADMIN_{callback.from_user.id}"
        )
        db.add(penalty_log)
        await db.commit()
        await RedisQueueService.remove_active_bridge(target_uid)

        # Kullanıcıya tebligat
        try:
            await callback.bot.send_message(
                chat_id=target_uid,
                text=(
                    f"⛔ <b>Sistemden Uzaklaştırıldınız</b>\n\n"
                    f"Hesabınız yöneticiler tarafından <b>{days} gün</b> süreyle sistemden uzaklaştırılmıştır.\n"
                    f"<b>Bitiş:</b> {format_date_short_tr(ban_until)}"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass

        await callback.answer(f"✅ {user.full_name} ({target_uid}) {days} gün uzaklaştırıldı!", show_alert=True)

    elif action == "unban":
        user.is_banned = False
        user.banned_until = None
        user.ban_reason = None
        await db.commit()

        try:
            await callback.bot.send_message(
                chat_id=target_uid,
                text="✅ Sistem kısıtlamanız yöneticiler tarafından kaldırılmıştır."
            )
        except Exception:
            pass

        await callback.answer(f"✅ {user.full_name} ({target_uid}) kısıtlaması kaldırıldı!", show_alert=True)

    elif action == "penalty":
        pts = val if val > 0 else 10
        await RankService.add_penalty_points(
            user_id=target_uid,
            points=pts,
            reason="Admin panelinden manuel ceza puanı",
            issued_by=f"ADMIN_{callback.from_user.id}",
            db=db
        )
        await callback.answer(f"✅ {user.full_name} ({target_uid}) hesabına +{pts} ceza puanı uygulandı!", show_alert=True)

    elif action == "rank":
        pts = val if val > 0 else 5
        user.rank_score += pts
        await db.commit()
        await callback.answer(f"⭐ {user.full_name} ({target_uid}) hesabına +{pts} rank puanı eklendi!", show_alert=True)

    # İlgili mesaj bir dosya kartı ise kartı güncelleyelim
    try:
        new_dossier = await render_user_profile_dossier(user, db)
        new_kb = build_user_admin_keyboard(user.id, is_banned=user.is_banned)
        await callback.message.edit_text(new_dossier, reply_markup=new_kb, parse_mode="HTML")
    except Exception:
        pass


@router.message(Command("kimdir", "kullanici_bilgi", "ihlal", "profil"))
async def cmd_user_info(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    args = message.text.split(maxsplit=1)
    target_identifier = None

    if len(args) >= 2:
        target_identifier = args[1].strip()
    elif message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot:
        target_identifier = str(message.reply_to_message.from_user.id)

    if not target_identifier:
        await message.reply("⚠️ Kullanım: <code>/kimdir &lt;@kullanici_adi veya ID&gt;</code>", parse_mode="HTML")
        return

    user = await find_user_by_query(target_identifier, db)
    if not user:
        await message.reply(
            f"❌ <b>'{target_identifier}'</b> kullanıcı adına, ID'sine veya ismine ait sistemde bir kayıt bulunamadı.\n"
            f"<i>Kullanıcının daha önce bota veya gruplara en az 1 kez mesaj atmış / başvurmuş olması gerekir.</i>",
            parse_mode="HTML"
        )
        return

    dossier = await render_user_profile_dossier(user, db)
    kb = build_user_admin_keyboard(user.id, is_banned=user.is_banned)
    await message.reply(dossier, reply_markup=kb, parse_mode="HTML")


async def find_user_by_query(query_str: str, db: AsyncSession) -> User:
    query_str = query_str.strip()
    user = None

    if query_str.isdigit():
        u_stmt = select(User).where(User.id == int(query_str))
        res = await db.execute(u_stmt)
        user = res.scalar_one_or_none()

    if not user:
        clean_uname = query_str.lstrip("@").lower()
        u_stmt = select(User).where(func.lower(User.username) == clean_uname)
        res = await db.execute(u_stmt)
        user = res.scalar_one_or_none()

    if not user:
        u_stmt = select(User).where(User.full_name.ilike(f"%{query_str}%"))
        res = await db.execute(u_stmt)
        user = res.scalar_one_or_none()

    return user


@router.message(Command("log", "ilan_log", "loglar", "kayitlar"))
async def cmd_listing_logs(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    args = message.text.split()
    listing_id = None
    if len(args) >= 2 and args[1].lstrip("#").isdigit():
        listing_id = int(args[1].lstrip("#"))
    elif message.reply_to_message:
        reply_txt = message.reply_to_message.text or message.reply_to_message.caption or ""
        id_m = re.search(r"(?:İlan|ilan|Listing|#)\s*#?(\d+)", reply_txt)
        if id_m:
            listing_id = int(id_m.group(1))

    if not listing_id:
        await message.reply("⚠️ Kullanım: <code>#12 log</code> veya <code>/log 12</code>", parse_mode="HTML")
        return

    dossier, kb = await render_listing_logs_dossier(listing_id, db)
    if dossier:
        await message.reply(dossier, reply_markup=kb, parse_mode="HTML")
    else:
        await message.reply(f"❌ <b>#{listing_id}</b> numaralı ilana ait kayıt bulunamadı.", parse_mode="HTML")


@router.message(F.chat.id == settings.admin_chat_id)
async def handle_admin_natural_query(message: Message, db: AsyncSession):
    text = (message.text or message.caption or "").strip()
    if not text:
        return

    # 0. "!test", "test komutları", "test rehberi" yakala
    if re.search(r"^(?:!test|/test|test\s+komutlar[ıi]|test\s+rehberi|test\s+menüsü)\b", text, re.IGNORECASE):
        guide = render_test_commands_guide()
        await message.reply(guide, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")
        return

    # 1. "#x log", "log #x", "x log", "ilan #x log" veya reply olarak "log" yakala
    log_match = re.search(r"#(\d+)\s+log(?:lar[ıi])?", text, re.IGNORECASE)
    if not log_match:
        log_match = re.search(r"\b(?:log|loglar[ıi]|kayıtlar[ıi])\s+#?(\d+)", text, re.IGNORECASE)
    if not log_match:
        log_match = re.search(r"\b(\d+)\s+log(?:lar[ıi])?", text, re.IGNORECASE)
    if not log_match:
        log_match = re.search(r"\bilan\s+#?(\d+)\s+log(?:lar[ıi])?", text, re.IGNORECASE)

    if not log_match and re.search(r"^\s*#?log(?:lar[ıi])?\s*$", text, re.IGNORECASE) and message.reply_to_message:
        reply_txt = message.reply_to_message.text or message.reply_to_message.caption or ""
        id_m = re.search(r"(?:İlan|ilan|Listing|#)\s*#?(\d+)", reply_txt)
        if id_m:
            listing_id = int(id_m.group(1))
            dossier, kb = await render_listing_logs_dossier(listing_id, db)
            if dossier:
                await message.reply(dossier, reply_markup=kb, parse_mode="HTML")
                return

    if log_match:
        listing_id = int(log_match.group(1))
        dossier, kb = await render_listing_logs_dossier(listing_id, db)
        if dossier:
            await message.reply(dossier, reply_markup=kb, parse_mode="HTML")
        else:
            await message.reply(f"❌ <b>#{listing_id}</b> numaralı ilana ait kayıt bulunamadı.", parse_mode="HTML")
        return

    # 2. Regex ile "@username kimdir", "username kimdir", "kimdir @username", "kimdir 123456" yakala
    match = re.search(r"@?([a-zA-Z0-9_]+)\s+kimdir\??", text, re.IGNORECASE)
    if not match:
        match = re.search(r"\bkimdir\s+@?([a-zA-Z0-9_]+)\??", text, re.IGNORECASE)

    target_identifier = None
    if match:
        target_identifier = match.group(1).strip()
    elif re.match(r"^\s*kimdir\s*\??$", text, re.IGNORECASE) and message.reply_to_message:
        reply_user = message.reply_to_message.from_user
        if reply_user and not reply_user.is_bot:
            target_identifier = str(reply_user.id)
        else:
            reply_text = message.reply_to_message.text or message.reply_to_message.caption or ""
            id_match = re.search(r"(?:ID|id|User ID):\s*<code>?(\d+)</code>?", reply_text)
            if id_match:
                target_identifier = id_match.group(1)

    if not target_identifier:
        return

    user = await find_user_by_query(target_identifier, db)
    if not user:
        await message.reply(
            f"❌ <b>'{target_identifier}'</b> sorgusuna ait sistemde kayıtlı kullanıcı bulunamadı.",
            parse_mode="HTML"
        )
        return

    dossier = await render_user_profile_dossier(user, db)
    kb = build_user_admin_keyboard(user.id, is_banned=user.is_banned)
    await message.reply(dossier, reply_markup=kb, parse_mode="HTML")


@router.message(Command("ilan_detay"))
async def cmd_listing_detail(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.reply("⚠️ Kullanım: <code>/ilan_detay &lt;ilan_id&gt;</code>", parse_mode="HTML")
        return

    try:
        listing_id = int(args[1].lstrip("#"))
    except ValueError:
        await message.reply("❌ Geçersiz İlan ID.")
        return

    queue_text = await get_listing_queue_text(listing_id, db)
    await message.reply(queue_text, parse_mode="HTML")


@router.message(Command("aktif_ilanlar"))
async def cmd_list_active(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    text = await get_active_sessions_text(db)
    await message.reply(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")


@router.message(Command("kara_liste"))
async def cmd_ban_list(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    text = await get_blacklist_text(db)
    await message.reply(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")


@router.message(Command("istatistik", "stats"))
async def cmd_stats(message: Message, db: AsyncSession):
    if not is_admin_chat(message):
        return

    text = await get_stats_text(db)
    await message.reply(text, reply_markup=get_admin_main_keyboard(), parse_mode="HTML")
