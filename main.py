import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, ALLOWED_GROUP_ID, OWNER_ID
from db.database import init_db, purge_old_ai_history, ensure_owner_marriage
from middlewares.user_middleware import UserMiddleware
from handlers import admin, ai_chat, links, reputation, economy, marriage, rp, triggers
from handlers import profile as profile_handler
from tasks.youtube import youtube_task

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# ── Авто-открепление постов из канала ─────────────────────────────
unpin_router = Router()


@unpin_router.channel_post()
async def auto_unpin_channel_post(message: Message, bot: Bot):
    """Канал публикует пост — Telegram закрепляет его в привязанной группе.
    Откреп через 1.5 сек."""
    await asyncio.sleep(1.5)
    try:
        await bot.unpin_chat_message(
            chat_id=message.chat.id,
            message_id=message.message_id
        )
    except Exception:
        pass


from aiogram import F as _F

@unpin_router.message(_F.is_automatic_forward == True)
async def auto_unpin_forwarded(message: Message, bot: Bot):
    """Автоматически пересланные посты из связанного канала в supergroup."""
    if message.chat.id not in ALLOWED_GROUP_ID:
        return
    await asyncio.sleep(1.5)
    try:
        await bot.unpin_chat_message(
            chat_id=message.chat.id,
            message_id=message.message_id
        )
    except Exception:
        pass


async def history_cleanup_task():
    """Авто-очистка ИИ-истории в БД каждые 3 дня + сброс in-memory кэша."""
    while True:
        await asyncio.sleep(3 * 24 * 60 * 60)
        try:
            await purge_old_ai_history(days=3)
            ai_chat._histories.clear()
            logging.info("✅ Авто-очистка истории ИИ выполнена.")
        except Exception as e:
            logging.error(f"❌ Ошибка очистки истории: {e}")


async def main():
    await init_db()
    await ensure_owner_marriage(OWNER_ID, ALLOWED_GROUP_ID)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Авто-открепление — до middleware, чтобы не блокировалось
    dp.include_router(unpin_router)

    dp.message.middleware(UserMiddleware())

    # Порядок важен:
    # 1. profile   — .start, .помощь, .профиль, .топ, .топреп
    # 2. admin     — модерация + персоны
    # 3. links     — .ссылки
    # 4. economy   — .баланс, .казино, .магазин, .ежедневная, .передать
    # 5. marriage  — .брак, .развод, .мойбрак, .браки, .гарем
    # 6. rp        — рп-команды
    # 7. triggers  — реакция на «фд» и спам (до reputation/ai_chat!)
    # 8. reputation — реакция на "+" и слова (до ai_chat!)
    # 9. ai_chat   — ловит всё остальное (последним!)
    dp.include_router(profile_handler.router)
    dp.include_router(admin.router)
    dp.include_router(links.router)
    dp.include_router(economy.router)
    dp.include_router(marriage.router)
    dp.include_router(rp.router)
    dp.include_router(triggers.router)
    dp.include_router(reputation.router)
    dp.include_router(ai_chat.router)

    logging.info("Бот запущен ✅")

    asyncio.create_task(youtube_task(bot))
    asyncio.create_task(history_cleanup_task())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
