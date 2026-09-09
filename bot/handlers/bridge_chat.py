from aiogram import Router, F
from aiogram.types import Message
from bot.services.redis_queue import RedisQueueService
from bot.services.bridge_service import BridgeService

router = Router()


@router.message(F.chat.type == "private", F.text.startswith("/"))
async def ignore_commands(message: Message):
    # Komutların bridge_chat tarafından yakalanmasını engelle
    pass


@router.message(F.chat.type == "private")
async def handle_private_bridge_message(message: Message):
    user_id = message.from_user.id
    bridge_info = await RedisQueueService.get_active_bridge(user_id)

    if not bridge_info:
        await message.reply(
            "ℹ️ <b>Şu anda aktif bir tevkil görüşmesinde değilsiniz.</b>\n\n"
            "Tevkil gruplarındaki ilanlara <code>[📋 Başvur]</code> butonuna tıklayarak katılabilir "
            "veya kendi ilanınızı <code>'tevkildir'</code> kelimesiyle paylaşabilirsiniz.",
            parse_mode="HTML"
        )
        return

    # Mesajı anonimleştirip partnerine ilet ve logla
    await BridgeService.forward_bridge_message(
        bot=message.bot,
        sender_msg=message,
        bridge_info=bridge_info
    )
