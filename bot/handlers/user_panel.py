from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.database.models import User, Listing, Application
from bot.services.rank_service import RankService
from bot.services.baro_service import BaroVerificationService
from bot.services.redis_queue import RedisQueueService
from bot.services.bridge_service import get_confirmation_keyboard
from bot.utils.time_utils import format_datetime_tr, format_date_short_tr

router = Router()


class BaroVerifyStates(StatesGroup):
    waiting_for_baro = State()
    waiting_for_sicil = State()
    waiting_for_document = State()


@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext, db: AsyncSession):
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

    # Parametre kontrolü (örn. /start chat_6 veya /start baro_verify)
    start_arg = None
    parts = (message.text or "").split()
    if len(parts) > 1:
        start_arg = parts[1].strip()

    if start_arg in ["baro_verify", "baro", "avukatlik_dogrula"]:
        if user.is_baro_verified:
            await message.reply(
                f"🎖️ <b>Sayın Av. {user.full_name}, Baro Kaydınız Zaten Doğrulanmıştır!</b>\n\n"
                f"• <b>Kayıtlı Baro:</b> {user.baro_name} Barosu\n"
                f"• <b>Sicil No:</b> {user.baro_sicil_no}\n"
                f"• <b>Net Rank Puanı:</b> ⭐ {net_score}\n\n"
                f"Grup içerisindeki tevkil ilanlarına <code>[📋 Başvur]</code> butonuna basarak doğrudan katılabilirsiniz.",
                parse_mode="HTML"
            )
            return

        await state.set_state(BaroVerifyStates.waiting_for_baro)
        kb = BaroVerificationService.get_baro_selection_keyboard()
        await message.reply(
            f"👋 <b>Merhaba Sayın {sender.full_name}, Hoş Geldiniz!</b>\n\n"
            f"🏛️ <b>AVUKATLIK / BARO LEVHA DOĞRULAMA ADIMI</b>\n\n"
            f"Tevkil ilanlarına öncelikli katılabilmek, bildirimleri anında alabilmek ve "
            f"<b>+10 Güven Puanı</b> ile <b>🎖️ 'Baro Onaylı Avukat'</b> rozetinizi almak için "
            f"lütfen bağlı olduğunuz baroyu seçiniz:",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    if start_arg and start_arg.startswith("chat_"):
        try:
            target_lid = int(start_arg.replace("chat_", ""))
            l_stmt = select(Listing).where(Listing.id == target_lid)
            l_res = await db.execute(l_stmt)
            target_listing = l_res.scalar_one_or_none()

            if not target_listing:
                await message.reply("❌ Tevkil ilanı bulunamadı.")
                return

            if target_listing.status in ["COMPLETED", "CLOSED_DISAGREED", "CANCELLED_TIMEOUT", "CANCELLED_ADMIN"]:
                await message.reply(
                    f"ℹ️ <b>Tevkil İlanı (#{target_lid})</b> tamamlanmış veya kapatılmıştır.\n"
                    f"Durum: <code>{target_listing.status}</code>",
                    parse_mode="HTML"
                )
                return

            # 1. İlan Sahibi İse:
            if sender.id == target_listing.creator_id:
                s_stmt = select(BridgeSession).where(BridgeSession.listing_id == target_lid, BridgeSession.is_active == True)
                s_res = await db.execute(s_stmt)
                active_sess = s_res.scalar_one_or_none()

                if active_sess:
                    await message.reply(
                        f"🔗 <b>Tevkil Görüşme Paneli (İlan #{target_lid})</b>\n\n"
                        f"👤 <b>Görüştüğünüz Kişi:</b> {active_sess.candidate_rank}. Sıradaki Başvuran Aday\n\n"
                        f"💬 <b>İletişim:</b> Bu sohbete yazacağınız her mesaj, fotoğraf, ses kaydı ve PDF "
                        f"karşı tarafa <b>anonim olarak iletilir</b>.\n\n"
                        f"Görüşme tamamlandığında aşağıdaki butonlardan durumu teyit edebilirsiniz:",
                        reply_markup=get_confirmation_keyboard(target_lid),
                        parse_mode="HTML"
                    )
                    return
                else:
                    await message.reply(
                        f"📌 <b>Tevkil İlanınız (#{target_lid})</b> yayındadır.\n"
                        f"Aday başvuruları beklenmektedir. Başvuru geldiğinde anında buradan bildirilecektir.",
                        parse_mode="HTML"
                    )
                    return

            # 2. Başvuran Aday İse:
            app_stmt = select(Application).where(Application.listing_id == target_lid, Application.user_id == sender.id)
            app_res = await db.execute(app_stmt)
            app_record = app_res.scalar_one_or_none()

            if app_record:
                if app_record.status == "ACTIVE":
                    await message.reply(
                        f"🔗 <b>Tevkil Görüşme Paneli (İlan #{target_lid})</b>\n\n"
                        f"👤 <b>Görüştüğünüz Kişi:</b> İlan Sahibi Meslektaşımız\n\n"
                        f"💬 <b>İletişim:</b> Bu sohbete yazacağınız her mesaj, fotoğraf, ses kaydı ve PDF "
                        f"ilan sahibine <b>anonim olarak iletilir</b>.\n\n"
                        f"Görüşme tamamlandığında veya vazgeçmek istediğinizde aşağıdaki butonlardan teyit edebilirsiniz:",
                        reply_markup=get_confirmation_keyboard(target_lid),
                        parse_mode="HTML"
                    )
                    return
                elif app_record.status == "WAITING":
                    await message.reply(
                        f"⏳ <b>Sayın Meslektaşımız (İlan #{target_lid})</b>\n\n"
                        f"Siz bu ilanda <b>{app_record.queue_number}. sıradaki yedek adaysınız</b>.\n"
                        f"Şu anda ilan sahibi 1. sıradaki meslektaşımız ile görüşmektedir.\n\n"
                        f"<i>Önceki adayla anlaşma sağlanamazsa sıra otomatik olarak size devredilecek ve buradan bilgilendirileceksiniz.</i>",
                        parse_mode="HTML"
                    )
                    return
                elif app_record.status == "ACCEPTED":
                    await message.reply(f"🤝 Bu ilan (#{target_lid}) için anlaşmanız onaylanmıştır.", parse_mode="HTML")
                    return
                else:
                    await message.reply(f"ℹ️ Bu ilan (#{target_lid}) için görüşmeniz sonlandırılmıştır.", parse_mode="HTML")
                    return
            else:
                await message.reply(
                    f"ℹ️ <b>İlan #{target_lid}</b> için henüz bir başvurunuz bulunmamaktadır.\n"
                    f"Gruptaki <b>[📋 Başvur (Sıraya Gir)]</b> butonuna tıklayarak sıraya girebilirsiniz.",
                    parse_mode="HTML"
                )
                return

        except Exception as e:
            print(f"[UserPanel] chat_ parametre ayrıştırma hatası: {e}")

    # Genel Aktif Köprü Kontrolü (DB doğrulamalı)
    active_bridge = await RedisQueueService.get_active_bridge(sender.id)
    if active_bridge:
        listing_id = active_bridge["listing_id"]
        role = active_bridge["role"]
        rank_idx = active_bridge.get("candidate_rank", 1)
        sess_id = active_bridge.get("session_id")

        # DB'de gerçekten aktif mi kontrol et
        s_stmt = select(BridgeSession).where(BridgeSession.id == sess_id)
        s_res = await db.execute(s_stmt)
        db_sess = s_res.scalar_one_or_none()

        if db_sess and db_sess.is_active:
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
        else:
            await RedisQueueService.remove_active_bridge(sender.id)

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
        "4. <b>🚨 TARİFE ALTI ÜCRET YASAĞI (DİREKT UZAKLAŞTIRMA):</b>\n"
        "   Baro Asgari Ücret Tarifesi / Grup Tarifesi altında ücret teklif edilmesi kesinlikle yasaktır. "
        "   Tarife altı teklif tespitinde ilgili kullanıcı <b>DİREKT SİSTEMDEN UZAKLAŞTIRILIR (+30 Ceza Puanı)</b>.\n\n"
        "5. <b>⏳ 30 Dakika Kuralı:</b>\n"
        "   Eşleşme sağlandıktan sonra ilan sahibi 30 dakika içinde adaya ilk mesajı göndermelidir. "
        "   Aksi halde ilan iptal edilir, hesaba <b>+20 Ceza Puanı</b> işlenir ve <b>5 gün sistemden uzaklaştırılır</b>.\n\n"
        "6. <b>🔒 Anonim Köprüleme:</b>\n"
        "   Görüşme bot üzerinden anonim yürütülür. Metin, fotoğraf, ses kaydı ve PDF dosyaları çift yönlü iletilir.\n\n"
        "7. <b>🤝 Anlaşma ve Sıra Devri:</b>\n"
        "   İlan sahibi <code>[🤝 Anlaştık]</code> ile tevkil sürecini tamamlar. "
        "   <code>[❌ Anlaşamadık]</code> seçilip 'Ücret' harici gerekçe belirtilirse sıra otomatik ve zincirleme olarak sıradaki adaya devredilir."
    )
    await message.reply(text, parse_mode="HTML")


from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery


class BaroVerifyStates(StatesGroup):
    waiting_for_baro = State()
    waiting_for_sicil = State()
    waiting_for_document = State()


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

    if user.is_baro_verified:
        baro_status = f"🎖️ <b>ONAYLI AVUKAT</b> ({user.baro_name} Barosu - Sicil: {user.baro_sicil_no})"
        baro_btn_text = "🔄 Baro Bilgilerimi Güncelle"
    elif user.baro_verification_status == "PENDING":
        baro_status = f"⏳ <b>ONAY BEKLİYOR</b> ({user.baro_name or 'Belirtilmedi'} - Sicil: {user.baro_sicil_no or 'Yok'})"
        baro_btn_text = "⏳ Doğrulama İnceleniyor"
    elif user.baro_verification_status == "REJECTED":
        baro_status = f"❌ <b>REDDEDİLDİ</b> (Yeniden başvuru için /baro_dogrula)"
        baro_btn_text = "🎖️ Yeniden Baro Doğrula"
    else:
        baro_status = "❌ <b>Doğrulanmadı</b> (/baro_dogrula)"
        baro_btn_text = "🎖️ Baro Kaydımı Doğrula (+10 Puan)"

    ban_status = f"⛔ <b>Kısıtlı:</b> {format_date_short_tr(user.banned_until)} tarihine kadar ({user.ban_reason})" if user.is_banned else "✅ <b>Aktif (Kısıtlama Yok)</b>"

    text = (
        f"👤 <b>KULLANICI PROFİL VE GÜVEN RAPORU</b>\n\n"
        f"• <b>Ad Soyad:</b> {user.full_name}\n"
        f"• <b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"• <b>Baro Durumu:</b> {baro_status}\n"
        f"• <b>Hesap Durumu:</b> {ban_status}\n\n"
        f"⭐ <b>Rank & Güven Puanı:</b>\n"
        f"• <b>Kazanılan Puan:</b> {user.rank_score}\n"
        f"• <b>Ceza Puanı:</b> {user.penalty_points}\n"
        f"• <b>Efektif Net Puan:</b> ⭐ <b>{net_score}</b> (Sistem Ortalaması: {avg_score:.1f})\n"
        f"• <b>Kademeli Sıra Handikapı:</b> {f'{handicap} Kademe' if handicap > 0 else 'Yok'}\n\n"
        f"📈 <b>İşlem İstatistikleri:</b>\n"
        f"• Tamamlanan Başarılı Tevkil: <b>{user.completed_tevkils_count}</b>\n"
        f"• İptal Edilen / Zaman Aşımı: <b>{user.cancelled_tevkils_count}</b>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=baro_btn_text, callback_data="user_act:start_baro_verify")]
    ])
    await message.reply(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "user_act:start_baro_verify")
async def handle_callback_baro_verify(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    await callback.answer()
    await state.set_state(BaroVerifyStates.waiting_for_baro)
    kb = BaroVerificationService.get_baro_selection_keyboard()
    await callback.message.reply(
        "🏛️ <b>AVUKATLIK / BARO LEVHA DOĞRULAMA SİSTEMİ</b>\n\n"
        "Lütfen kayıtlı olduğunuz baroyu aşağıdaki butonlardan seçiniz veya "
        "<b>[✍️ Diğer Baroyu Kendim Yazacağım]</b> seçeneğine tıklayınız:\n\n"
        "<i>(Doğrulanmış meslektaşlarımıza 🎖️ 'Baro Onaylı Avukat' rozeti ve +10 Güven Puanı verilir.)</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.message(Command("baro_dogrula", "baro_kaydet", "avukatlik_dogrula", "avukat_dogrula"), F.chat.type == "private")
async def cmd_baro_verify(message: Message, state: FSMContext, db: AsyncSession):
    parts = message.text.split(maxsplit=2)
    if len(parts) >= 3:
        # Hızlı argümanlı kayıt: /baro_kaydet İstanbul 12345
        baro_name = parts[1]
        sicil_no = parts[2]
        res = await BaroVerificationService.submit_verification_request(
            bot=message.bot,
            user_id=message.from_user.id,
            baro_name=baro_name,
            sicil_no=sicil_no,
            db=db
        )
        await message.reply(res["message"], parse_mode="HTML")
        return

    # İnteraktif Sihirbazı Başlat
    await state.set_state(BaroVerifyStates.waiting_for_baro)
    kb = BaroVerificationService.get_baro_selection_keyboard()
    await message.reply(
        "🏛️ <b>AVUKATLIK / BARO LEVHA DOĞRULAMA SİSTEMİ</b>\n\n"
        "Lütfen kayıtlı olduğunuz baroyu aşağıdaki butonlardan seçiniz:\n\n"
        "<i>(Doğrulanan meslektaşlarımıza profilinde 🎖️ 'Baro Onaylı Avukat' rozeti ve +10 Güven Puanı verilir.)</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("baro_sel:"))
async def handle_baro_selection_callback(callback: CallbackQuery, state: FSMContext):
    selected = callback.data.split(":", 1)[1]
    if selected == "CANCEL":
        await state.clear()
        await callback.answer("İşlem iptal edildi.")
        try:
            await callback.message.edit_text("❌ Baro doğrulama işlemi iptal edildi.")
        except Exception:
            pass
        return

    if selected == "OTHER":
        await callback.answer()
        await callback.message.reply(
            "✍️ Lütfen bağlı olduğunuz baro adını yazınız:\n"
            "<i>(Örn: Çanakkale, Trabzon, Şanlıurfa, Denizli, Diyarbakır vb.)</i>",
            parse_mode="HTML"
        )
        await state.set_state(BaroVerifyStates.waiting_for_baro)
        return

    # Popüler butonlardan seçildi
    await callback.answer()
    norm_baro = BaroVerificationService.normalize_baro_name(selected) or selected
    await state.update_data(baro_name=norm_baro)
    await state.set_state(BaroVerifyStates.waiting_for_sicil)

    await callback.message.reply(
        f"🏛️ <b>Seçilen Baro:</b> {norm_baro} Barosu\n\n"
        f"Lütfen <b>Baro Sicil Numaranızı</b> yazınız:\n"
        f"<i>(Örn: <code>12345</code>)</i>",
        parse_mode="HTML"
    )


@router.message(BaroVerifyStates.waiting_for_baro, F.chat.type == "private")
async def handle_baro_text_input(message: Message, state: FSMContext):
    raw_text = (message.text or "").strip()
    norm_baro = BaroVerificationService.normalize_baro_name(raw_text) or raw_text

    await state.update_data(baro_name=norm_baro)
    await state.set_state(BaroVerifyStates.waiting_for_sicil)

    await message.reply(
        f"🏛️ <b>Kayıtlı Baro:</b> {norm_baro} Barosu\n\n"
        f"Lütfen <b>Baro Sicil Numaranızı</b> yazınız:\n"
        f"<i>(Örn: <code>12345</code>)</i>",
        parse_mode="HTML"
    )


@router.message(BaroVerifyStates.waiting_for_sicil, F.chat.type == "private")
async def handle_sicil_input(message: Message, state: FSMContext):
    sicil_raw = (message.text or "").strip()
    if not BaroVerificationService.validate_sicil_format(sicil_raw):
        await message.reply(
            "⚠️ <b>Geçersiz Sicil Formatı:</b> Sicil numarası sadece 3 ila 7 basamaklı rakamlardan oluşmalıdır.\n"
            "Lütfen tekrar deneyiniz (Örn: <code>12345</code>):",
            parse_mode="HTML"
        )
        return

    await state.update_data(sicil_no=sicil_raw)
    await state.set_state(BaroVerifyStates.waiting_for_document)

    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Belgesiz Gönder (Sadece Beyan)", callback_data="baro_skip_doc")]
    ])

    await message.reply(
        f"📄 <b>Son Adım: Avukatlık Belgesi / Kimlik Fotoğrafı (İsteğe Bağlı)</b>\n\n"
        f"• <b>Baro:</b> {(await state.get_data()).get('baro_name')} Barosu\n"
        f"• <b>Sicil No:</b> {sicil_raw}\n\n"
        f"Doğrulama sürecinizi hızlandırmak ve anında <b>🎖️ Onaylı Avukat Rozeti</b> almak için "
        f"lütfen <b>Baro Kimlik Kartınızın</b> veya <b>E-Devlet Barkodlu Avukatlık Belgenizin</b> fotoğrafını ya da PDF dosyasını buraya gönderiniz.\n\n"
        f"<i>(Belge göndermek istemiyorsanız aşağıdaki 'Belgesiz Gönder' butonuna basabilirsiniz.)</i>",
        reply_markup=skip_kb,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "baro_skip_doc")
async def handle_baro_skip_document(callback: CallbackQuery, state: FSMContext, db: AsyncSession):
    await callback.answer()
    data = await state.get_data()
    baro_name = data.get("baro_name", "İstanbul")
    sicil_no = data.get("sicil_no", "12345")
    await state.clear()

    res = await BaroVerificationService.submit_verification_request(
        bot=callback.bot,
        user_id=callback.from_user.id,
        baro_name=baro_name,
        sicil_no=sicil_no,
        document_file_id=None,
        db=db
    )
    try:
        await callback.message.edit_text(res["message"], parse_mode="HTML")
    except Exception:
        await callback.message.reply(res["message"], parse_mode="HTML")


@router.message(BaroVerifyStates.waiting_for_document, F.chat.type == "private")
async def handle_baro_document_upload(message: Message, state: FSMContext, db: AsyncSession):
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id

    data = await state.get_data()
    baro_name = data.get("baro_name", "İstanbul")
    sicil_no = data.get("sicil_no", "12345")
    await state.clear()

    res = await BaroVerificationService.submit_verification_request(
        bot=message.bot,
        user_id=message.from_user.id,
        baro_name=baro_name,
        sicil_no=sicil_no,
        document_file_id=file_id,
        db=db
    )
    await message.reply(res["message"], parse_mode="HTML")


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
