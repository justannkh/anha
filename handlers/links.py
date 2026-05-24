from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import (
    LINK_TG_CHANNEL, LINK_BOOSTI, LINK_ARCHIVE, LINK_YOUTUBE_CH
)

router = Router()
P = "."


@router.message(Command("ссылки", "links", prefix=P))
async def cmd_links(message: Message):
    lines = ["🔗 <b>Наши платформы</b>\n"]

    if LINK_TG_CHANNEL:
        lines.append(f"  📢 <b>Telegram-канал:</b> {LINK_TG_CHANNEL}")
    if LINK_BOOSTI:
        lines.append(f"  💎 <b>Бусти:</b> {LINK_BOOSTI}")
    if LINK_ARCHIVE:
        lines.append(f"  📚 <b>Архив:</b> {LINK_ARCHIVE}")
    if LINK_YOUTUBE_CH:
        lines.append(f"  📺 <b>YouTube-канал:</b> {LINK_YOUTUBE_CH}")

    if len(lines) == 1:
        return await message.answer("🔗 Ссылки ещё не настроены. Заполни LINK_* в .env.")

    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
