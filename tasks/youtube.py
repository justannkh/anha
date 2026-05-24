"""
Фоновая задача: проверяет RSS YouTube-канала каждые 30 минут.
Если появилось ДЕЙСТВИТЕЛЬНО НОВОЕ видео (НЕ Shorts, вышло < 2 часов назад)
— постит его в Telegram-канал.

При первом запуске просто запоминает текущее видео БЕЗ публикации.
"""
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import aiohttp
from aiogram import Bot

from config import YOUTUBE_CHANNEL_ID, PUBLISH_CHANNEL_ID
from db.database import (
    get_setting, set_setting, purge_old_ai_history,
    purge_old_proposals, purge_old_cooldowns,
)

log = logging.getLogger(__name__)

YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt":   "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

# Максимальный возраст видео для публикации (2 часа).
# Если видео старше — считаем его не новым, даже если ID не совпадает.
MAX_VIDEO_AGE = timedelta(hours=2)

_last_purge: datetime | None = None


async def _is_short(video_id: str) -> bool:
    """Проверяет, является ли видео Shorts (HEAD /shorts/ID → 200 = Shorts)."""
    shorts_url = f"https://www.youtube.com/shorts/{video_id}"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.head(shorts_url, allow_redirects=False) as resp:
                return resp.status == 200
    except Exception as e:
        log.warning("Shorts check error for %s: %s", video_id, e)
        return False


def _parse_published(entry) -> datetime | None:
    """Парсит дату публикации из RSS entry."""
    published = entry.findtext("atom:published", namespaces=NS)
    if not published:
        return None
    try:
        # YouTube формат: 2025-03-15T12:30:00+00:00
        return datetime.fromisoformat(published.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def _fetch_latest_video() -> tuple[str, str, str, datetime | None] | None:
    """
    Возвращает (video_id, title, url, published_dt) последнего обычного видео
    (НЕ Shorts) или None.
    """
    if not YOUTUBE_CHANNEL_ID:
        return None
    url = YT_FEED.format(channel_id=YOUTUBE_CHANNEL_ID)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    log.warning("YouTube RSS: HTTP %s", resp.status)
                    return None
                text = await resp.text()
        root = ET.fromstring(text)
        entries = root.findall("atom:entry", NS)
        if not entries:
            return None

        for entry in entries[:10]:
            vid_id = entry.findtext("yt:videoId", namespaces=NS) or ""
            title = entry.findtext("atom:title", namespaces=NS) or ""

            if not vid_id:
                continue

            if await _is_short(vid_id):
                log.info("Skipping Shorts: %s (%s)", vid_id, title)
                continue

            published_dt = _parse_published(entry)
            vid_url = f"https://www.youtube.com/watch?v={vid_id}"
            return vid_id, title, vid_url, published_dt

        return None
    except Exception as e:
        log.error("YouTube fetch error: %s", e)
        return None


async def check_new_video(bot: Bot):
    """Проверяет наличие нового видео и постит в канал."""
    if not PUBLISH_CHANNEL_ID or not YOUTUBE_CHANNEL_ID:
        return

    result = await _fetch_latest_video()
    if not result:
        return

    vid_id, title, vid_url, published_dt = result
    stored_id = await get_setting("yt_last_video_id")

    # Если ID совпадает — видео уже обработано
    if vid_id == stored_id:
        return

    # ── ПЕРВЫЙ ЗАПУСК ────────────────────────────────────────────
    # Если stored_id пустой — бот запущен впервые.
    # Просто запоминаем текущее видео БЕЗ публикации.
    if not stored_id:
        await set_setting("yt_last_video_id", vid_id)
        await set_setting("yt_last_video_url", vid_url)
        await set_setting("yt_last_video_title", title)
        log.info("First run: saved current video without posting: %s", title)
        return

    # ── ПРОВЕРКА ДАТЫ ПУБЛИКАЦИИ ─────────────────────────────────
    # Постим только если видео вышло менее MAX_VIDEO_AGE назад.
    # Это защищает от ситуации, когда бот был выключен долго,
    # а потом при перезапуске нашёл "новый" ID (старое видео).
    now = datetime.now(timezone.utc)
    if published_dt:
        video_age = now - published_dt
        if video_age > MAX_VIDEO_AGE:
            # Видео слишком старое — просто запоминаем, не постим
            await set_setting("yt_last_video_id", vid_id)
            await set_setting("yt_last_video_url", vid_url)
            await set_setting("yt_last_video_title", title)
            log.info("Video too old (%s ago), saving without posting: %s",
                     video_age, title)
            return
    else:
        # Не удалось распарсить дату — на всякий случай не постим,
        # просто запоминаем
        await set_setting("yt_last_video_id", vid_id)
        await set_setting("yt_last_video_url", vid_url)
        await set_setting("yt_last_video_title", title)
        log.warning("Could not parse publish date, saving without posting: %s", title)
        return

    # ── ПУБЛИКУЕМ ────────────────────────────────────────────────
    await set_setting("yt_last_video_id", vid_id)
    await set_setting("yt_last_video_url", vid_url)
    await set_setting("yt_last_video_title", title)

    try:
        await bot.send_message(
            chat_id=PUBLISH_CHANNEL_ID,
            text=(
                f"🔴 <b>Новое видео!</b>\n\n"
                f"🎬 {title}\n\n"
                f"{vid_url}"
            ),
            parse_mode="HTML",
        )
        log.info("Posted new YouTube video: %s (age: %s)", title, video_age)
    except Exception as e:
        log.error("Failed to post video to channel: %s", e)


async def _maybe_purge():
    """Чистит устаревшие данные раз в 3 дня."""
    global _last_purge
    now = datetime.now(timezone.utc)
    if _last_purge is None or (now - _last_purge).days >= 3:
        await purge_old_ai_history(days=3)
        await purge_old_proposals(hours=24)
        await purge_old_cooldowns(seconds=3600)
        _last_purge = now
        log.info("Periodic cleanup done.")


async def youtube_task(bot: Bot):
    """Основной цикл фоновой задачи."""
    log.info("YouTube monitor started.")
    await asyncio.sleep(10)

    while True:
        try:
            await check_new_video(bot)
            await _maybe_purge()
        except Exception as e:
            log.error("youtube_task error: %s", e)
        await asyncio.sleep(1800)  # каждые 30 минут
