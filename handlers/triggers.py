import re
import time
import random

from aiogram import Router, F
from aiogram.types import Message

from config import (
    FD_REPLIES, SPAM_REPLIES,
    SPAM_WINDOW, SPAM_MAX_MSGS, SPAM_REPEAT_LIMIT, SPAM_NOTIFY_COOLDOWN,
)

router = Router()

# ══════════════════════════════════════════════════════════════════
#  ТРИГГЕР НА «ФД» / FACING DEMONS
#  Реагирует на упоминание фд и его вариаций (рус/англ).
# ══════════════════════════════════════════════════════════════════


# Регулярка ловит:
#   фд / фд!  (как отдельное слово)
#   фейсинг/фэйсинг демонс/демон  (рус)
#   facing demon(s)  (англ)
_FD_RE = re.compile(
    r"""
    (?:^|[^а-яёa-z])          # граница слева (не буква)
    (?:
        фд                    # просто «фд»
      | ф[еэ]йсинг\s*демон(?:с|s)?   # фейсинг/фэйсинг демон(с)
      | facing\s*demon(?:s)?         # facing demon(s)
      | fd                    # англ «fd» как отдельное слово
    )
    (?:$|[^а-яёa-z])          # граница справа (не буква)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_fd_message(message: Message) -> bool:
    text = (message.text or "")
    if not text:
        return False
    # игнорируем команды
    if text.startswith(".") or text.startswith("/"):
        return False
    return bool(_FD_RE.search(text))


@router.message(F.func(_is_fd_message))
async def fd_handler(message: Message):
    await message.reply(random.choice(FD_REPLIES))


# ══════════════════════════════════════════════════════════════════
#  АНТИ-СПАМ ТРИГГЕР
#  Ловит флуд (много одинаковых сообщений подряд), длинные простыни
#  из повторяющихся символов и слишком частые сообщения.
#  Анха делает замечание (без модерации — просто реакция).
# ══════════════════════════════════════════════════════════════════



# Состояние по юзерам
_msg_times: dict[int, list[float]] = {}
_last_text: dict[int, tuple[str, int]] = {}   # user_id -> (последний текст, счётчик повторов)
_last_notify: dict[int, float] = {}


def _has_long_char_run(text: str, run: int = 12) -> bool:
    """True, если в тексте есть длинная цепочка одного символа (ааааааа...)."""
    return re.search(r"(.)\1{" + str(run - 1) + r",}", text) is not None


def _looks_like_spam(user_id: int, text: str) -> bool:
    now = time.time()

    # 1) Частота сообщений
    bucket = [t for t in _msg_times.get(user_id, []) if t > now - SPAM_WINDOW]
    bucket.append(now)
    _msg_times[user_id] = bucket
    flood_by_rate = len(bucket) >= SPAM_MAX_MSGS

    # 2) Повтор одного и того же текста
    norm = text.strip().lower()
    prev_text, repeat = _last_text.get(user_id, ("", 0))
    if norm and norm == prev_text:
        repeat += 1
    else:
        repeat = 1
    _last_text[user_id] = (norm, repeat)
    flood_by_repeat = repeat >= SPAM_REPEAT_LIMIT

    # 3) Длинная простыня из одного символа
    flood_by_chars = _has_long_char_run(text)

    return flood_by_rate or flood_by_repeat or flood_by_chars


def _is_spam_message(message: Message) -> bool:
    text = (message.text or "")
    if not text:
        return False
    if text.startswith(".") or text.startswith("/"):
        return False
    return _looks_like_spam(message.from_user.id, text)


@router.message(F.func(_is_spam_message))
async def spam_handler(message: Message):
    uid = message.from_user.id
    now = time.time()
    # Не долбим замечаниями — не чаще раза в SPAM_NOTIFY_COOLDOWN секунд
    if now - _last_notify.get(uid, 0) < SPAM_NOTIFY_COOLDOWN:
        return
    _last_notify[uid] = now
    await message.reply(random.choice(SPAM_REPLIES))
