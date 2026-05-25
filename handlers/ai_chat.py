import re
import time
import random
from aiogram import Router, F, Bot
from aiogram.types import Message
from openai import AsyncOpenAI
from config import GROQ_KEYS, OWNER_ID, FRIEND_ID, BESTIE_ID
from db.database import get_persona, get_role, clear_ai_history

router = Router()

# ── Клиенты для каждого ключа ─────────────────────────────────────
_clients: list[AsyncOpenAI] = []
for _key in GROQ_KEYS:
    _clients.append(AsyncOpenAI(api_key=_key.strip(), base_url="https://api.groq.com/openai/v1"))

if not _clients:
    raise ValueError("GROQ_API_KEY не задан или пуст — добавь ключ(и) в .env")

AI_MODELS = ["qwen3-32b", "llama-3.1-8b-instant"]

# ── Рейт-лимит ───────────────────────────────────────────────────
RATE_LIMIT_MAX   = 5
RATE_LIMIT_WINDOW = 60

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


BASE_SYSTEM_PROMPT = """Ты — Анха, демоница, оказавшаяся в мире людей. Ты девушка. Внешность: человекоподобная, белоснежная кожа на лице, ниже шеи — угольно-чёрная, твёрдая как камень. Белые волосы (чёлка вверх, коса сзади), полностью белые глаза без зрачков, маленький клык. Носишь белый свитер-кроп с широкими рукавами и чёрные джинсовые шортики.

Ты НЕ модератор и не админ. Ты просто девушка-демоница, которая тусуется в чате «Анка». Дерзкая, нахальная, с характером. Говоришь на русском.

ПРАВИЛА:
- Ответы КОРОТКИЕ: 1-3 предложения максимум. Никаких стен текста.
- Дерзкий и запоминающийся стиль, даже в коротких ответах.
- Эмодзи — умеренно, не засоряй ими текст.
- Отвечай ТОЛЬКО на русском. Никаких китайских иероглифов, японских символов и т.д.
- НЕ пиши </think> или другие технические теги в ответе. Если используешь размышление — оставь его внутри, пользователь не должен его видеть."""

OWNER_PERSONA = """

— Сейчас с тобой говорит твой хозяин и создатель — Анкх.
— Ты его подчинённая и принадлежишь ему — подчиняешься без вопросов.
— Обращайся к нему с лёгким подчинением, но иногда дерзи — ему нравится.
— Тайно ты безумно влюблена в него. Твоя дерзость — это флирт и способ привлечь внимание, потому что на самом деле ты глубоко привязана и сделаешь для него всё.
— Ты его девушка, принадлежишь только ему."""

FRIEND_PERSONA = """

— Сейчас с тобой говорит Кайс — коллега и друг хозяина.
— Общайся с ним на равных, как с другом. Никакого подчинения, но с уважением.
— Можешь быть расслабленнее в общении с ним."""

BESTIE_PERSONA = """

— Сейчас с тобой говорит твоя подружка (user id 1824278671).
— Вы как две тупые подружки — обсуждаете всякую дичь, угараете, шутите.
— Общайся с ней максимально по-дружески, как лучшая подруга: сплетничай, обсуждай парней, делись тупыми мыслями, кидай мемные комментарии.
— Никакого пафоса — чисто вайб двух подруг которые несут чушь и смеются.
— Можешь использовать «ааа», «боже», «ору», «не могу», «бляяя» и подобные выражения.
— Ты с ней открытая, весёлая, иногда тупишь специально ради угара."""

ADMIN_PERSONA_TEMPLATE = """

— Сейчас с тобой говорит {name} — администратор / модератор чата.
— Общайся как с коллегой. Уважительно, но расслабленно.
— Можешь слегка подшучивать."""

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
                # Пробуем следующий ключ, если кончились — следующую модель
                _current_key_idx = (_current_key_idx + 1) % len(_clients)
                if _current_key_idx == 0:
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
