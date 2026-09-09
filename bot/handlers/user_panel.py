from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.database.models import User, Listing, Application
from bot.services.rank_service import RankService
from bot.services.baro_service import BaroVerificationService
from bot.services.redis_queue import RedisQueueService
from bot.services.bridge_service import get_confirmation_keyboard
from bot.utils.time_utils import format_datetime_tr, format_date_short_tr

router = Router()


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, db: AsyncSession):
    sender = message.from_user
    u_stmt = select(User).where(User.id == sender.id)
    res = await db.execute(u_stmt)
    user = res.scalar_one_or_none()

    if not user:
        user = User(
            id=sender.id,
            username=sender.username,
            full_name=sender.full_name or "",
            rank_score=100,
            penalty_points=0
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    net_score = RankService.calculate_net_score(user.rank_score, user.penalty_points)
    avg_score = await RankService.get_system_average_score(db)
    handicap = RankService.determine_handicap_level(net_score, avg_score, user.penalty_points)

    # Bekleyen mesajlar varsa anında ilet
    from bot.services.bridge_service import BridgeService
    await BridgeService.flush_pending_messages(message.bot, sender.id)

    # Aktif bir köprü görüşmesi var mı kontrol et
    active_bridge = await RedisQueueService.get_active_bridge(sender.id)
    if active_bridge:
        listing_id = active_bridge["listing_id"]
        role = active_bridge["role"]
        rank_idx = active_bridge.get("candidate_rank", 1)

        if role == "CREATOR":
            await message.reply(
                f"🔗 <b>Aktif Tevkil Görüşmeniz Bulunmaktadır! (İlan #{listing_id})</b>\n\n"
                f"👤 <b>Görüştüğünüz Kişi:</b> {rank_idx}. Sıradaki Başvuran Aday\n\n"
                f"💬 <b>İletişim:</b> Bu sohbete yazacağınız her mesaj, fotoğraf, ses kaydı ve PDF "
                f"karşı tarafa <b>anonim olarak iletilir</b>.\n\n"
                f"Görüşme tamamlandığında aşağıdaki butonlardan durumu teyit edebilirsiniz:",
                reply_markup=get_confirmation_keyboard(listing_id),
                parse_mode="HTML"
            )
            return
        else:
            await message.reply(
                f"🔗 <b>Aktif Tevkil Görüşmeniz Bulunmaktadır! (İlan #{listing_id})</b>\n\n"
                f"👤 <b>Görüştüğünüz Kişi:</b> İlan Sahibi Meslektaşımız\n\n"
                f"💬 <b>İletişim:</b> Bu sohbete yazacağınız her mesaj, fotoğraf, ses kaydı ve PDF "
                f"ilan sahibine <b>anonim olarak iletilir</b>.\n\n"
                f"Görüşme tamamlandığında veya vazgeçmek istediğinizde aşağıdaki butonlardan teyit edebilirsiniz:",
                reply_markup=get_confirmation_keyboard(listing_id),
                parse_mode="HTML"
            )
            return

    handicap_text = f"⚠️ <b>Aktif Sıra Handikapı:</b> Seviye {handicap}" if handicap > 0 else "✅ <b>Handikap Durumu:</b> Yok (Öncelikli Başvuru)"

    text = (
        f"👋 <b>Merhaba Sayın {sender.full_name}, Tevkil Botu'na Hoş Geldiniz!</b>\n\n"
        f"Bu bot, Telegram hukuk gruplarındaki tevkil ilanlarını milisaniye hassasiyetli adil bir sıra sistemiyle yönetir, "
        f"tarafları gizlilik esasıyla anonim olarak buluşturur.\n\n"
        f"📊 <b>Profil Bilgileriniz:</b>\n"
        f"• <b>Rank Puanı:</b> ⭐ <code>{net_score}</code>\n"
        f"• <b>Ceza Puanı:</b> <code>{user.penalty_points}</code>\n"
        f"• <b>Tamamlanan Tevkil:</b> <code>{user.completed_tevkils_count}</code>\n"
        f"• {handicap_text}\n\n"
        f"ℹ️ <b>Kullanabileceğiniz Komutlar:</b>\n"
        f"• <code>/yardim</code> - Sistem kuralları ve işleyiş rehberi\n"
        f"• <code>/profilim</code> - Detaylı durum ve ceza sorgulama\n"
        f"• <code>/ilanlarim</code> - Açtığınız tevkil ilanları\n"
        f"• <code>/basvurularim</code> - Yaptığınız başvurular\n"
        f"• <code>/baro_kaydet &lt;Baro&gt; &lt;SicilNo&gt;</code> - Baro levha doğrulama\n"
    )
    await message.reply(text, parse_mode="HTML")


@router.message(Command("yardim", "help"), F.chat.type == "private")
async def cmd_help(message: Message):
    text = (
        "📚 <b>TEVKİL BOTU KULLANIM REHBERİ VE KURALLAR</b>\n\n"
        "1. <b>İlan Açma:</b>\n"
        "   Hukuk gruplarında paylaştığınız mesajda <code>'tevkildir'</code> veya adliye olan il/ilçe adı "
        "   (örn. Bursa, Bayramiç, Çağlayan vb.) ile duruşma/evrak bilgisi geçmelidir. "
        "   Bot ilanınızı otomatik algılar, mesajınızı siler ve grupta anonim butonlu pano oluşturur.\n\n"
        "2. <b>Milisaniye Sıralama Sistemi:</b>\n"
        "   Butona tıklayan meslektaşlarımız milisaniye hassasiyetiyle sıraya alınır. "
        "   Sadece 1. sıradaki meslektaşımızla doğrudan DM görüşmesi başlatılır.\n\n"
        "3. <b>⭐ Rank ve Kademeli Handikap Sistemi:</b>\n"
        "   • Başarıyla tamamlanan her tevkil için taraflara <b>+5 Puan</b> verilir.\n"
        "   • Ceza puanı olan veya sistem ortalaması altındaki kullanıcılar başvuru yaptığında "
        "   puanına göre <b>1-2-3-4 sıra geriden</b> başlayacak şekilde adil handikap uygulanır.\n\n"
        "4. <b>🚨 TARİFE ALTI ÜCRET YASAĞI (DİREKT BAN):</b>\n"
        "   Baro Asgari Ücret Tarifesi / Grup Tarifesi altında ücret teklif edilmesi kesinlikle yasaktır. "
        "   Tarife altı teklif tespitinde ilgili kullanıcı <b>DİREKT BANLANIR (+30 Ceza Puanı)</b>.\n\n"
        "5. <b>⏳ 30 Dakika Kuralı:</b>\n"
        "   Eşleşme sağlandıktan sonra ilan sahibi 30 dakika içinde adaya ilk mesajı göndermelidir. "
        "   Aksi halde ilan iptal edilir, hesaba <b>+20 Ceza Puanı</b> işlenir ve <b>5 gün sistemden men</b> edilir.\n\n"
        "6. <b>🔒 Anonim Köprüleme:</b>\n"
        "   Görüşme bot üzerinden anonim yürütülür. Metin, fotoğraf, ses kaydı ve PDF dosyaları çift yönlü iletilir.\n\n"
        "7. <b>🤝 Anlaşma ve Sıra Devri:</b>\n"
        "   İlan sahibi <code>[🤝 Anlaştık]</code> ile tevkil sürecini tamamlar. "
        "   <code>[❌ Anlaşamadık]</code> seçilip 'Ücret' harici gerekçe belirtilirse sıra otomatik ve zincirleme olarak sıradaki adaya devredilir."
    )
    await message.reply(text, parse_mode="HTML")


@router.message(Command("profilim", "durum"), F.chat.type == "private")
async def cmd_profile(message: Message, db: AsyncSession):
    sender = message.from_user
    u_stmt = select(User).where(User.id == sender.id)
    res = await db.execute(u_stmt)
    user = res.scalar_one_or_none()

    if not user:
        await message.reply("Kullanıcı kaydınız bulunamadı. Lütfen /start yazınız.")
        return

    net_score = RankService.calculate_net_score(user.rank_score, user.penalty_points)
    avg_score = await RankService.get_system_average_score(db)
    handicap = RankService.determine_handicap_level(net_score, avg_score, user.penalty_points)

    baro_status = f"✅ {user.baro_name} ({user.baro_sicil_no})" if user.is_baro_verified else "❌ Doğrulanmadı (/baro_kaydet)"
    ban_status = f"⛔ <b>Kısıtlı:</b> {format_date_short_tr(user.banned_until)} tarihine kadar ({user.ban_reason})" if user.is_banned else "✅ <b>Aktif (Kısıtlama Yok)</b>"

    text = (
        f"👤 <b>KULLANICI PROFİL VE RANK RAPORU</b>\n\n"
        f"• <b>Ad Soyad:</b> {user.full_name}\n"
        f"• <b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"• <b>Baro Doğrulama:</b> {baro_status}\n"
        f"• <b>Durum:</b> {ban_status}\n\n"
        f"⭐ <b>Rank Puanı Bilgileri:</b>\n"
        f"• <b>Kazanılan Puan:</b> {user.rank_score}\n"
        f"• <b>Ceza Puanı:</b> {user.penalty_points}\n"
        f"• <b>Efektif Net Puan:</b> ⭐ <b>{net_score}</b> (Sistem Ortalaması: {avg_score:.1f})\n"
        f"• <b>Kademeli Sıra Handikapı:</b> {f'{handicap} Kademe' if handicap > 0 else 'Yok'}\n\n"
        f"📈 <b>İşlem İstatistikleri:</b>\n"
        f"• Tamamlanan Başarılı Tevkil: <b>{user.completed_tevkils_count}</b>\n"
        f"• İptal Edilen / Zaman Aşımı: <b>{user.cancelled_tevkils_count}</b>"
    )
    await message.reply(text, parse_mode="HTML")


@router.message(Command("ilanlarim"), F.chat.type == "private")
async def cmd_my_listings(message: Message, db: AsyncSession):
    sender = message.from_user
    stmt = (
        select(Listing)
        .where(Listing.creator_id == sender.id)
        .order_by(Listing.id.desc())
        .limit(10)
    )
    res = await db.execute(stmt)
    listings = res.scalars().all()

    if not listings:
        await message.reply("Henüz yayınlanmış bir tevkil ilanınız bulunmamaktadır.")
        return

    lines = ["📋 <b>Son Tevkil İlanlarınız:</b>\n"]
    for l in listings:
        lines.append(
            f"• <b>İlan #{l.id}</b> | Durum: <code>{l.status}</code>\n"
            f"  Tarih: {format_date_short_tr(l.created_at)}\n"
            f"  İçerik: <i>{l.raw_text[:80]}...</i>\n"
        )
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("basvurularim"), F.chat.type == "private")
async def cmd_my_applications(message: Message, db: AsyncSession):
    sender = message.from_user
    stmt = (
        select(Application)
        .where(Application.user_id == sender.id)
        .order_by(Application.id.desc())
        .limit(10)
    )
    res = await db.execute(stmt)
    apps = res.scalars().all()

    if not apps:
        await message.reply("Henüz bir tevkil ilanına başvurunuz bulunmamaktadır.")
        return

    lines = ["📋 <b>Son Başvurularınız:</b>\n"]
    for a in apps:
        lines.append(
            f"• <b>İlan #{a.listing_id}</b> | Sıra: <b>{a.queue_number}.</b> | Durum: <code>{a.status}</code>\n"
            f"  Puan: ⭐ {a.user_rank_score} | Tarih: {format_date_short_tr(a.applied_at)}\n"
        )
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("baro_kaydet"), F.chat.type == "private")
async def cmd_baro_verify(message: Message, db: AsyncSession):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply(
            "⚠️ Kullanım: <code>/baro_kaydet &lt;Baro_Adı&gt; &lt;Sicil_No&gt;</code>\n"
            "<i>Örnek: /baro_kaydet İstanbul 12345</i>",
            parse_mode="HTML"
        )
        return

    baro_name = parts[1]
    sicil_no = parts[2]

    res = await BaroVerificationService.verify_lawyer_credentials(
        user_id=message.from_user.id,
        baro_name=baro_name,
        sicil_no=sicil_no,
        db=db
    )
    await message.reply(res["message"])
