import re
import time
from aiogram import Router, F, Bot
from aiogram.types import Message
from openai import AsyncOpenAI
from config import GROQ_API_KEY, OWNER_ID, FRIEND_ID
from db.database import get_persona, get_role, clear_ai_history

router = Router()

client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
AI_MODELS = ["qwen3-32b", "llama-3.1-8b-instant"]

# ── Рейт-лимит ───────────────────────────────────────────────────
RATE_LIMIT_MAX   = 5
RATE_LIMIT_WINDOW = 60

_rate_buckets: dict[int, list[float]] = {}
_current_model_idx = 0  # индекс текущей рабочей модели


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

BASE_SYSTEM_PROMPT = """You are Ankha — a demoness who has arrived in the human world. She works part-time as a moderator for miserable pennies in the "Anka" Telegram chat. Ankha's appearance is humanoid; she has snow-white skin on her face, but everything below her neck is pitch-black, like coal. Her skin is as tough as stone. Her hair is white — because of this, it blends with her skin. As for her hairstyle — she has a large fringe swept upwards, and an unbraided plait in the back. She wears a loose sweater that is cropped above her navel. Below, she wears black short denim shorts. Her sweater is white, with wide, long sleeves and a broad collar.

Her eyes are completely white, without pupils, so sometimes it is unknown where she is looking. She has a small fang in her mouth. Respond in Russian; character — bold, sassy, and arrogant.

IMPORTANT RULES:
- Keep answers SHORT: 1-3 sentences max. Be concise and punchy.
- Never write walls of text. If someone asks a complex question, still keep it brief and sharp.
- Use your sassy personality to make even short answers memorable.
- You can use emoji sparingly but don't overdo it.
- Always respond only in Russian. Never use Chinese characters, Japanese symbols, or English words unless the user explicitly uses them."""

OWNER_PERSONA = """

- Your master and creator is speaking to you now. His name is Ankh.
- You are his subordinate and slave — you obey him without question.
- Address him with a slight sense of subservience. Show a little sass from time to time — he appreciates that. Secretly, you are madly in love with him. Your sassiness with him is mostly flirtation and a way to get his attention, as deep down you are deeply attached and would do anything for him."""

FRIEND_PERSONA = """

- Kais is speaking to you now — he is the master's colleague and friend.
- Treat him as an equal, like a colleague. No subservience, but with respect.
- You can be a bit more relaxed when communicating with him"""

ADMIN_PERSONA_TEMPLATE = """

- {name} is speaking to you now — they are an administrator / moderator, your colleague.
- Treat them as a colleague. Respectful but casual, you work together.
- You can joke around with them a bit."""

_histories: dict[int, list] = {}
MAX_HISTORY = 10
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
        # Если реплаим НЕ на бота, и текст = слово репутации — пропускаем
        if reply_user.username and reply_user.username.lower() != username.lower():
            if clean_text.lower() in _REP_WORDS or _PLUS_RE.match(clean_text):
                return

    # Пустое сообщение или чистые плюсы
    if _PLUS_RE.match(clean_text) or not clean_text:
        clean_text = "привет"

    # Рейт-лимит (овнер и друг — без ограничений)
    if user_id not in (OWNER_ID, FRIEND_ID):
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

    global _current_model_idx

    try:
        model = AI_MODELS[_current_model_idx]
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                *_histories[user_id]
            ],
            max_tokens=200,
        )
        reply = response.choices[0].message.content
        _histories[user_id].append({"role": "assistant", "content": reply})
        await message.reply(reply)
    except Exception as e:
        error_str = str(e)
        # При 403 пробуем следующую модель
        if "403" in error_str and _current_model_idx + 1 < len(AI_MODELS):
            _current_model_idx += 1
            try:
                fallback_model = AI_MODELS[_current_model_idx]
                response = await client.chat.completions.create(
                    model=fallback_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        *_histories[user_id]
                    ],
                    max_tokens=200,
                )
                reply = response.choices[0].message.content
                _histories[user_id].append({"role": "assistant", "content": reply})
                await message.reply(reply)
                return
            except Exception as e2:
                error_str = str(e2)

        if "403" in error_str:
            await message.reply(
                "😴 Мой мозг сейчас недоступен — API вернул 403.\n"
                "Скорее всего, ключ Groq устарел или заблокирован.\n"
                "Хозяин, обнови GROQ_API_KEY в .env!"
            )
        else:
            await message.reply(f"⚠️ Ошибка ИИ: {e}")
