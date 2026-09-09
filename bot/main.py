import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.database.connection import init_db
from bot.services.redis_queue import redis_client
from bot.middlewares.db_session import DbSessionMiddleware
from bot.middlewares.blacklist_check import BlacklistMiddleware
from bot.handlers import (
    admin_panel,
    group_detector,
    application,
    confirmation,
    bridge_chat
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Bot başlatılıyor...")

    # Veritabanı tablolarını oluştur
    await init_db()
    logger.info("Veritabanı tabloları doğrulandı.")

    # Redis bağlantı kontrolü
    try:
        await redis_client.ping()
        logger.info("Redis bağlantısı başarılı.")
    except Exception as e:
        logger.error(f"Redis bağlantı hatası: {e}")
        raise

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()

    # Global Middlewares
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.message.outer_middleware(BlacklistMiddleware())
    dp.callback_query.outer_middleware(BlacklistMiddleware())

    # Routers Kaydı
    dp.include_router(admin_panel.router)
    dp.include_router(group_detector.router)
    dp.include_router(application.router)
    dp.include_router(confirmation.router)
    dp.include_router(bridge_chat.router)

    logger.info(f"Bot çalışmaya hazır. Admin Grubu: {settings.admin_chat_id}")
    
    # Eski bekleyen güncellemeleri temizle ve polling başlat
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot durduruldu.")
