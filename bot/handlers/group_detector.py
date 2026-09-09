import re
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.database.models import User, Listing
from bot.services.audit_service import AuditService
from bot.services.rank_service import RankService
from bot.utils.time_utils import get_current_istanbul_time
from bot.utils.courthouses import TURKISH_COURTHOUSES, normalize_text_for_search

router = Router()

TASK_CONTEXT_KEYWORDS = [
    r"\bdurusma\w*",
    r"\bkatilacak\w*",
    r"\bgirecek\w*",
    r"\bgirebilecek\w*",
    r"\bkatilabilecek\w*",
    r"\bgidebilecek\w*",
    r"\bmeslektas\w*",
    r"\bavukat\w*",
    r"\bevrak\w*",
    r"\bdosya\w*",
    r"\bhaciz\w*",
    r"\bicra\w*",
    r"\bkesif\w*",
    r"\bteslim\w*",
    r"\bfotokopi\w*",
    r"\bkalem\w*",
    r"\byetki\s*belges\w*",
    r"\badliye\w*",
    r"\bmahkeme\w*",
    r"\bkurum\w*",
    r"\bdevlet\s*kurum\w*",
    r"\bvar\s*mi\w*",
    r"\byardimci\w*",
    r"\btevkil\w*"
]

NEGATIVE_PATTERNS = [
    r"\btevkil\s+degildir\b",
    r"\btevkildir\s+degildir\b",
    r"\btevkil\s+degil\b",
    r"\btevkil\s+degildir\w*",
    r"\btevkil\s+amaciyla\s+degil\b",
]


def is_tevkil_message(text: str) -> bool:
    if not text:
        return False

    norm = normalize_text_for_search(text)

    for neg_pat in NEGATIVE_PATTERNS:
        if re.search(neg_pat, norm):
            return False

    if re.search(r"\btevkildir\b", norm):
        return True

    words = re.findall(r"[a-z0-9]+", norm)
    has_courthouse = False

    for w in words:
        if w in TURKISH_COURTHOUSES:
            has_courthouse = True
            break

    if not has_courthouse:
        for ch in TURKISH_COURTHOUSES:
            if " " in ch and ch in norm:
                has_courthouse = True
                break

    if has_courthouse:
        for pat in TASK_CONTEXT_KEYWORDS:
            if re.search(pat, norm):
                return True

    return False


def build_apply_keyboard(listing_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Başvur (Sıraya Gir)",
                    callback_data=f"apply:{listing_id}"
                )
            ]
        ]
    )


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def detect_tevkil_post(message: Message, db: AsyncSession):
    text = message.text or message.caption
    if not text or not is_tevkil_message(text):
        return

    sender = message.from_user
    if not sender:
        return

    # 1. Kullanıcıyı DB'ye kaydet veya güncelle
    user_stmt = select(User).where(User.id == sender.id)
    res = await db.execute(user_stmt)
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
    else:
        user.username = sender.username
        user.full_name = sender.full_name or user.full_name
        await db.commit()

    # Eğer ilan sahibi kısıtlıysa ilanı işleme alma ve uyar
    if user.is_banned:
        time_str = user.banned_until.strftime("%d.%m.%Y %H:%M") if user.banned_until else ""
        await message.reply(
            f"⛔ <b>Sayın Meslektaşımız,</b> hesabınız {time_str} tarihine kadar "
            f"kısıtlı olduğundan tevkil ilanı açamazsınız.",
            parse_mode="HTML"
        )
        return

    # 2. Listing kaydı oluştur
    listing = Listing(
        group_id=message.chat.id,
        group_title=message.chat.title,
        message_id=message.message_id,
        creator_id=sender.id,
        raw_text=text,
        status="OPEN",
        created_at=datetime.utcnow()
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)

    # 3. Özelden Mesaj Atılmasını Engellemek İçin Orijinal Mesajı Silmeyi Dene
    is_deleted = False
    try:
        await message.delete()
        is_deleted = True
    except Exception:
        is_deleted = False

    # 4. Grupta Anonim İlan Mesajı Yayınla
    now_istanbul = get_current_istanbul_time()
    now_str = now_istanbul.strftime("%H:%M:%S")
    net_score = RankService.calculate_net_score(user.rank_score, user.penalty_points)
    
    reply_text = (
        f"📌 <b>YENİ TEVKİL İLANI (#{listing.id})</b>\n"
        f"👤 <b>İlan Sahibi:</b> Meslektaşımız (⭐ {net_score} Puan)\n"
        f"🕒 <b>Yayın Zamanı:</b> <code>{now_str}</code>\n\n"
        f"📝 <b>İlan İçeriği:</b>\n"
        f"<i>{text}</i>\n\n"
        f"📋 <b>Canlı Başvuru Sıralaması:</b>\n"
        f"<i>(Henüz başvuru yapılmadı. İlk tıklayan görüşme hakkı kazanır.)</i>\n\n"
        f"🚨 <b>ÖNEMLİ:</b> İlan sahibine özelden yazmak ve tarife altı teklif vermek <b>DİREKT BAN</b> sebebidir!\n"
        f"ℹ️ <i>Başvuran meslektaşlarımızın DM bildirimleri alabilmesi için @Tevkil_Denetim_Merkezi_bot botunu başlatması gerekmektedir.</i>\n\n"
        f"👇 <i>Aşağıdaki butona tıklayarak adil sıraya girebilirsiniz:</i>"
    )

    if is_deleted:
        sent_msg = await message.bot.send_message(
            chat_id=message.chat.id,
            text=reply_text,
            reply_markup=build_apply_keyboard(listing.id),
            parse_mode="HTML"
        )
    else:
        sent_msg = await message.reply(
            text=reply_text,
            reply_markup=build_apply_keyboard(listing.id),
            parse_mode="HTML"
        )

    listing.bot_reply_message_id = sent_msg.message_id
    await db.commit()

    # 5. İlan Sahibine Özel Mesajla Doğrulama ve Güvenlik Uyarısı Gönder
    try:
        await message.bot.send_message(
            chat_id=sender.id,
            text=(
                f"✅ <b>Tevkil İlanınız Yayınlandı (#{listing.id})</b>\n\n"
                f"İlanınız grupta güvenli ve anonim olarak paylaşıldı.\n\n"
                f"🛡️ <b>Güvenlik & Sıra Uyarısı:</b>\n"
                f"• Gruptan profilinize tıklayıp 'hemen yaparım' vb. diyerek harici özel mesaj atanları <b>kesinlikle dikkate almayınız</b>.\n"
                f"• Süreç yalnızca butona tıklayan 1. sıradaki meslektaşımızla bot üzerinden yürütülecektir.\n"
                f"• Başvuru geldiğinde buradan anında bilgilendirileceksiniz."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    # 6. Admin Denetim Grubuna bilgilendirme geç
    await AuditService.notify_admin_event(
        bot=message.bot,
        text=(
            f"📢 <b>[YENİ İLAN TESPİT EDİLDİ]</b>\n"
            f"📋 <b>İlan ID:</b> #{listing.id}\n"
            f"👥 <b>Grup:</b> {message.chat.title} (<code>{message.chat.id}</code>)\n"
            f"👤 <b>İlan Sahibi:</b> {sender.full_name} (@{sender.username or 'yok'}) [ID: <code>{sender.id}</code>] (⭐ {net_score} Puan)\n"
            f"📝 <b>İlan Metni:</b>\n{text[:500]}"
        )
    )
