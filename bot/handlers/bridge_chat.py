from aiogram import Router, F
from aiogram.types import Message
from bot.database.connection import AsyncSessionLocal
from bot.services.redis_queue import RedisQueueService
from bot.services.bridge_service import BridgeService, get_confirmation_keyboard
from bot.handlers.confirmation import execute_agree_step, get_reason_keyboard

router = Router()

AGREE_TRIGGERS = {
    "🤝 anlaştık", "🤝 anlastik", "anlaştık", "anlastik",
    "/anlastik", "/anlaş", "/anlas", "/onay", "/kabul",
    "anlaştım", "anlastim"
}

DISAGREE_TRIGGERS = {
    "❌ anlaşamadık", "❌ anlasamadik", "anlaşamadık", "anlasamadik",
    "/anlasamadik", "/iptal", "/red", "/vazgec"
}

STATUS_TRIGGERS = {
    "/durum", "/menu", "/menü", "/status", "/yardim", "/yardım", "/komutlar"
}


@router.message(F.chat.type == "private")
async def handle_private_bridge_message(message: Message):
    user_id = message.from_user.id
    bridge_info = await RedisQueueService.get_active_bridge(user_id)

    # 1. Aktif köprü oturumu yoksa
    if not bridge_info:
        if message.text and message.text.startswith("/"):
            return
        await message.reply(
            "ℹ️ <b>Şu anda aktif bir tevkil görüşmesinde değilsiniz.</b>\n\n"
            "Tevkil gruplarındaki ilanlara <code>[📋 Başvur]</code> butonuna tıklayarak katılabilir "
            "veya kendi ilanınızı <code>'tevkildir'</code> kelimesiyle paylaşabilirsiniz.",
            parse_mode="HTML"
        )
        return

    raw_text = (message.text or "").strip().lower()
    listing_id = bridge_info["listing_id"]
    role = bridge_info.get("role", "APPLICANT")

    # 2. Anlaştık Tetikleyicisi (Alt menü butonu veya metin/komut)
    if raw_text in AGREE_TRIGGERS:
        async with AsyncSessionLocal() as db:
            await execute_agree_step(
                bot=message.bot,
                user_id=user_id,
                listing_id=listing_id,
                db=db,
                message=message
            )
        return

    # 3. Anlaşamadık Tetikleyicisi (Alt menü butonu veya metin/komut)
    if raw_text in DISAGREE_TRIGGERS:
        role_prefix = "creator" if role == "CREATOR" else "applicant"
        await message.reply(
            "❌ <b>Anlaşamama Sebebini Belirtiniz:</b>\n\n"
            "Lütfen meslektaşınızla anlaşamama gerekçenizi seçiniz.\n"
            "🚨 <b>Önemli Kural:</b> Tarife altı ücret tekliflerinde sistem tarafından <b>DİREKT SİSTEMDEN UZAKLAŞTIRMA</b> yaptırımı uygulanır:",
            reply_markup=get_reason_keyboard(listing_id, role_prefix=role_prefix),
            parse_mode="HTML"
        )
        return

    # 4. Durum / Menü Tetikleyicisi
    if raw_text in STATUS_TRIGGERS:
        await message.reply(
            f"📌 <b>Aktif Görüşme Durumu (#{listing_id})</b>\n\n"
            f"Görüşmeniz şu anda aktiftir.\n\n"
            f"• Görüşmeyi onaylamak için <b>[🤝 Anlaştık]</b>\n"
            f"• Görüşmeyi sonlandırmak için <b>[❌ Anlaşamadık]</b>\n\n"
            f"<i>(Bu butonları ekranınızın altındaki menüden de dilediğiniz an tek tıkla kullanabilirsiniz.)</i>",
            reply_markup=get_confirmation_keyboard(listing_id),
            parse_mode="HTML"
        )
        return

    # 5. Diğer / ile başlayan komutlar (köprüye mesaj olarak gitmesin)
    if message.text and message.text.startswith("/"):
        return

    # 6. Normal Görüşme Mesajı (Metin, Fotoğraf, Belge, Ses) -> Karşı tarafa anonim ilet ve logla
    await BridgeService.forward_bridge_message(
        bot=message.bot,
        sender_msg=message,
        bridge_info=bridge_info
    )
