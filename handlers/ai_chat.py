import re
import time
import random
from aiogram import Router, F, Bot
from aiogram.types import Message
from openai import AsyncOpenAI
from config import (
    GROQ_KEYS, OWNER_ID, FRIEND_ID, BESTIE_ID,
    RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, MAX_HISTORY,
    BASE_SYSTEM_PROMPT, OWNER_PERSONA, FRIEND_PERSONA,
    BESTIE_PERSONA, ADMIN_PERSONA_TEMPLATE,
)
from db.database import get_persona, get_role, clear_ai_history

router = Router()

# ── Клиенты для каждого ключа ─────────────────────────────────────
_clients: list[AsyncOpenAI] = []
for _key in GROQ_KEYS:
    _clients.append(AsyncOpenAI(api_key=_key.strip(), base_url="https://api.groq.com/openai/v1"))

if not _clients:
    raise ValueError("GROQ_API_KEY не задан или пуст — добавь ключ(и) в .env")

# Модели Groq. ВАЖНО: ID моделей должны быть полными (с префиксом),
# иначе Groq вернёт 404 model_not_found.
# Идём по списку сверху вниз: если первая недоступна/перегружена — берём следующую.
AI_MODELS = [
    "llama-3.3-70b-versatile",   # основная: умная, быстрая, отлично знает русский
    "qwen/qwen3-32b",            # запасная №1 (раньше тут был неверный "qwen3-32b")
    "openai/gpt-oss-120b",       # запасная №2
    "llama-3.1-8b-instant",      # лёгкая, на самый крайний случай
]

# ── Рейт-лимит (настройки в config.py) ───────────────────────────
_rate_buckets: dict[int, list[float]] = {}
_current_model_idx = 0
_current_key_idx   = 0


def _check_rate_limit(user_id: int) -> tuple[bool, int]:
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    if user_id not in _rate_buckets:
        _rate_buckets[user_id] = []
    _rate_buckets[user_id] = [t for t in _rate_buckets[user_id] if t > cutoff]
    if len(_rate_buckets[user_id]) >= RATE_LIMIT_MAX:
        oldest = _rate_buckets[user_id][0]
        wait = int(oldest + RATE_LIMIT_WINDOW - now) + 1
        return False, max(wait, 1)
    _rate_buckets[user_id].append(now)
    return True, 0


def _get_client() -> AsyncOpenAI:
    return _clients[_current_key_idx % len(_clients)]


# Персоны ИИ берутся из config.py (BASE_SYSTEM_PROMPT, *_PERSONA, ADMIN_PERSONA_TEMPLATE)

_histories: dict[int, list] = {}
_bot_username: str | None = None
_PLUS_RE = re.compile(r'^\++$')


async def _get_bot_username(bot: Bot) -> str:
    global _bot_username
    if _bot_username is None:
        me = await bot.get_me()
        _bot_username = me.username
    return _bot_username


async def _build_system_prompt(user_id: int, username: str | None, full_name: str) -> str:
    if user_id == OWNER_ID:
        return BASE_SYSTEM_PROMPT + OWNER_PERSONA

    if user_id == FRIEND_ID:
        return BASE_SYSTEM_PROMPT + FRIEND_PERSONA

    if user_id == BESTIE_ID:
        return BASE_SYSTEM_PROMPT + BESTIE_PERSONA

    # Админы и модеры — коллеги
    role = await get_role(user_id)
    if role in ("admin", "moder"):
        return BASE_SYSTEM_PROMPT + ADMIN_PERSONA_TEMPLATE.format(name=full_name)

    persona = await get_persona(user_id)
    if not persona:
        return BASE_SYSTEM_PROMPT

    nick     = persona.get("nick") or full_name
    name_str = f"@{username}" if username else full_name
    extra = (
        f"\n\n— Сейчас с тобой говорит {full_name} ({name_str}), ты знаешь его как «{nick}»."
        f"\n— Тон общения: {persona['tone']}"
    )
    if persona.get("facts"):
        extra += f"\n— Что ты о нём знаешь: {persona['facts']}"
    return BASE_SYSTEM_PROMPT + extra


# Слова для репутации — чтобы не перехватывать их в ИИ
_REP_WORDS = {
    "респект", "уважение", "увожение", "красавчик", "красава",
    "жиза", "жыза", "лайк", "молодец", "спасибо", "благодарю",
    "топ", "база", "класс", "круто", "огонь", "шик", "найс",
    "имба", "годнота", "согласен", "справедливо", "правильно",
    "лучший", "гений", "мастер", "легенда", "царь", "кинг",
    "братан", "бро",
    "f", "respect", "like", "nice", "based", "goat", "fire",
    "king", "legend", "w", "гг", "gg", "wp",
}


def _clean_think_tags(text: str) -> str:
    """Удаляет теги <think>...</think> и мусор типа </think> из ответа модели."""
    # Удаляем полные блоки <think>...</think>
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Удаляем оставшиеся открывающие/закрывающие теги
    text = re.sub(r'</?think>', '', text)
    return text.strip()


@router.message(F.text & ~F.text.startswith("."))
async def ai_handler(message: Message, bot: Bot):
    text = message.text or ""

    username = await _get_bot_username(bot)

    is_mention   = f"@{username}".lower() in text.lower()
    is_reply_bot = (
        message.reply_to_message is not None
        and message.reply_to_message.from_user is not None
        and message.reply_to_message.from_user.username is not None
        and message.reply_to_message.from_user.username.lower() == username.lower()
    )

    if not is_mention and not is_reply_bot:
        return

    user      = message.from_user
    user_id   = user.id
    clean_text = text.replace(f"@{username}", "").strip()

    # Не перехватываем репутационные слова при реплае на чужое сообщение
    if message.reply_to_message and message.reply_to_message.from_user:
        reply_user = message.reply_to_message.from_user
        if reply_user.username and reply_user.username.lower() != username.lower():
            if clean_text.lower() in _REP_WORDS or _PLUS_RE.match(clean_text):
                return

    # Пустое сообщение или чистые плюсы
    if _PLUS_RE.match(clean_text) or not clean_text:
        clean_text = "привет"

    # Рейт-лимит (овнер, друг и подружка — без ограничений)
    if user_id not in (OWNER_ID, FRIEND_ID, BESTIE_ID):
        allowed, wait_sec = _check_rate_limit(user_id)
        if not allowed:
            return await message.reply(
                f"⏳ Тише, смертный. {RATE_LIMIT_MAX} сообщений в минуту — твой потолок.\n"
                f"Жди ещё <b>{wait_sec}</b> сек.",
                parse_mode="HTML"
            )

    if user_id not in _histories:
        _histories[user_id] = []

    _histories[user_id].append({"role": "user", "content": clean_text})
    if len(_histories[user_id]) > MAX_HISTORY:
        _histories[user_id] = _histories[user_id][-MAX_HISTORY:]

    await bot.send_chat_action(message.chat.id, "typing")
    system_prompt = await _build_system_prompt(user_id, user.username, user.full_name)

    global _current_model_idx, _current_key_idx

    # Пробуем все комбинации ключ × модель
    last_error = None
    for _attempt in range(len(_clients) * len(AI_MODELS)):
        client = _get_client()
        model = AI_MODELS[_current_model_idx]
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *_histories[user_id]
                ],
                max_tokens=200,
            )
            reply = response.choices[0].message.content
            reply = _clean_think_tags(reply)
            if not reply:
                reply = "..."
            _histories[user_id].append({"role": "assistant", "content": reply})
            await message.reply(reply)
            return
        except Exception as e:
            last_error = e
            error_str = str(e)
            if "403" in error_str or "429" in error_str or "401" in error_str:
                # Кончился лимит/доступ по ключу — пробуем следующий ключ,
                # если ключи кончились — переходим на следующую модель
                _current_key_idx = (_current_key_idx + 1) % len(_clients)
                if _current_key_idx == 0:
                    _current_model_idx = (_current_model_idx + 1) % len(AI_MODELS)
            elif (
                "404" in error_str
                or "model_not_found" in error_str
                or "does not exist" in error_str
                or "400" in error_str
                or "decommissioned" in error_str
            ):
                # Модель недоступна/устарела — сразу пробуем следующую модель
                _current_model_idx = (_current_model_idx + 1) % len(AI_MODELS)
            else:
                break

    # Все попытки провалились
    error_str = str(last_error) if last_error else "Неизвестная ошибка"
    if "403" in error_str or "401" in error_str:
        await message.reply(
            "😴 Мой мозг сейчас недоступен — API вернул 403.\n"
            "Скорее всего, ключ Groq устарел или заблокирован.\n"
            "Хозяин, обнови GROQ_API_KEY в .env!"
        )
    else:
        await message.reply(f"⚠️ Ошибка ИИ: {last_error}")
