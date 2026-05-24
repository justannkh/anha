import re
import random
from aiogram import Router, F
from aiogram.types import Message

from db.database import add_reputation, get_user, check_rep_cooldown, set_rep_cooldown, count_rep_received_today

router = Router()

# Макс. 20 получений репутации в день на одного юзера (защита от мультиакков)
MAX_REP_RECEIVED_PER_DAY = 20

# Расширенный список слов для повышения репутации
_PLUS_RE = re.compile(r'^\++$')
_REP_WORDS = {
    # Русские
    "респект", "уважение", "увожение", "красавчик", "красава",
    "жиза", "жыза", "лайк", "молодец", "спасибо", "благодарю",
    "топ", "база", "класс", "круто", "огонь", "шик", "найс",
    "имба", "годнота", "согласен", "справедливо", "правильно",
    "лучший", "гений", "мастер", "легенда", "царь", "кинг",
    "братан", "бро",
    # Английские
    "f", "respect", "like", "nice", "based", "goat", "fire",
    "king", "legend", "w", "гг", "gg", "wp",
}

# Фразы для случайного ответа при репутации
_REP_PHRASES = [
    "Заслуженно! 🌟",
    "Уважение — это важно. ✨",
    "Так и запишем. 📝",
    "Плюсик в карму! ⭐",
    "Репутация растёт! 📈",
    "Одобрено. 👑",
    "Уровень уважения повышен! 🎯",
]


def _is_rep_message(message: Message) -> bool:
    """Фильтр: текст = реп-слово/плюсы, реплай на не-бота, не на себя."""
    text = (message.text or "").strip().lower()
    if not text:
        return False
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return False
    target = message.reply_to_message.from_user
    if target.is_bot:
        return False
    if target.id == message.from_user.id:
        return False
    return bool(_PLUS_RE.match(text)) or text in _REP_WORDS


@router.message(F.func(_is_rep_message))
async def rep_handler(message: Message):
    text = (message.text or "").strip().lower()

    target_user = message.reply_to_message.from_user
    if target_user.id == message.from_user.id:
        return await message.answer("😏 Сам себя не похвалишь — никто не похвалит? Нет, так не работает.")

    target_db = await get_user(target_user.id)
    if not target_db:
        return

    # Проверяем кулдаун (1 час между одним и тем же юзером)
    on_cd = await check_rep_cooldown(message.from_user.id, target_user.id, seconds=3600)
    if on_cd:
        return await message.answer(
            "⏳ Ты уже давал репутацию этому юзеру недавно.\n"
            "Подожди немного перед следующим разом.",
            parse_mode="HTML"
        )

    # Лимит получения: макс N раз в день на одного юзера (защита от мультиакков)
    received_today = await count_rep_received_today(target_user.id)
    if received_today >= MAX_REP_RECEIVED_PER_DAY:
        return await message.answer(
            f"📊 <b>{target_user.full_name}</b> уже получил максимум репутации на сегодня.\n"
            "Попробуй завтра!",
            parse_mode="HTML"
        )

    is_plus = bool(_PLUS_RE.match(text))
    if is_plus:
        amount = min(len(text), 5)
    else:
        amount = 1

    new_rep = await add_reputation(target_user.id, amount)
    await set_rep_cooldown(message.from_user.id, target_user.id)

    plus_str = "+" * amount
    phrase = random.choice(_REP_PHRASES)

    await message.answer(
        f"✨ <b>{target_user.full_name}</b> получает <b>{plus_str}</b> к репутации.\n"
        f"📊 Итого: <b>{new_rep}</b> ✨\n\n"
        f"<i>{phrase}</i>",
        parse_mode="HTML"
    )
