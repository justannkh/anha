import random
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message

from db.database import get_user, get_user_by_username

# Гифки — заполняются в rp_gifs.py
try:
    from rp_gifs import RP_GIFS
except ImportError:
    RP_GIFS = {}

router = Router()
P = "."

# ══════════════════════════════════════════════════════════════════
#  РП-КОМАНДЫ — действия от третьего лица
# ══════════════════════════════════════════════════════════════════

RP_ACTIONS = {
    "обнять": ("обнимает", "🤗", [
        "Обнимашки ебать",
    ]),
    "ударить": ("бьёт", "👊", [
        "Одной левой!",
    ]),
    "поцеловать": ("целует", "💋", [
        "Кайс ушёл блевать",
    ]),
    "погладить": ("гладит", "🥰", [
        "Хороший мальчик, на лапу",
    ]),
    "укусить": ("кусает", "😈", [
        "Бешенство передано успешно",
    ]),
    "пнуть": ("пинает", "🦵", [
        "Улетел в закат нахер",
    ]),
    "убить": ("убивает", "💀", [
        "F в чат, пацаны",
    ]),
    "шлёпнуть": ("шлёпает", "🫲", [
        "За шо? За дело!",
    ]),
    "потыкать": ("тыкает", "👉", [
        "Тык-тык, ты живой вообще?",
    ]),
    "выстрелить": ("стреляет в", "🔫", [
        "360 noscope, легко",
    ]),
    "лизнуть": ("лижет", "👅", [
        "Зачем... просто зачем",
    ]),
    "дать_пять": ("даёт пять", "🙏", [
        "Братья по разуму (оба без него)",
    ]),
    "подмигнуть": ("подмигивает", "😏", [
        "Сус момент 📸",
    ]),
    "накормить": ("кормит", "🍕", [
        "Жуй и молчи, тебе идёт",
    ]),
    "напоить": ("наливает чай для", "🍵", [
        "Чаёк подъехал, не благодари",
    ]),
    # ── 18+ команды ──────────────────────────────────────────────
    "связать": ("связывает", "⛓", [
        "Ну всё, попался голубчик",
    ]),
    "отшлёпать": ("шлёпает по попе", "🍑", [
        "Плохое поведение — больная попа",
    ]),
    "придушить": ("слегка придушивает", "🫠", [
        "Тише... тише... вот так",
    ]),
    "засосать": ("засасывает", "💜", [
        "Шарфик завтра наденешь",
    ]),
    "сесть_на": ("садится на колени к", "🦵😏", [
        "Терпи, я лёгкая (нет)",
    ]),
}

# Алиасы
RP_ALIASES = {
    "обнять": "обнять",
    "хаг": "обнять",
    "hug": "обнять",
    "ударить": "ударить",
    "хит": "ударить",
    "hit": "ударить",
    "стукнуть": "ударить",
    "поцеловать": "поцеловать",
    "кисс": "поцеловать",
    "kiss": "поцеловать",
    "чмокнуть": "поцеловать",
    "погладить": "погладить",
    "пэт": "погладить",
    "pat": "погладить",
    "укусить": "укусить",
    "кусь": "укусить",
    "bite": "укусить",
    "пнуть": "пнуть",
    "kick": "пнуть",
    "кикнуть": "пнуть",
    "убить": "убить",
    "kill": "убить",
    "шлёпнуть": "шлёпнуть",
    "шлепнуть": "шлёпнуть",
    "slap": "шлёпнуть",
    "потыкать": "потыкать",
    "тыкнуть": "потыкать",
    "poke": "потыкать",
    "выстрелить": "выстрелить",
    "shoot": "выстрелить",
    "лизнуть": "лизнуть",
    "lick": "лизнуть",
    "дать_пять": "дать_пять",
    "дай_пять": "дать_пять",
    "five": "дать_пять",
    "подмигнуть": "подмигнуть",
    "wink": "подмигнуть",
    "накормить": "накормить",
    "feed": "накормить",
    "напоить": "напоить",
    # 18+
    "связать": "связать",
    "tie": "связать",
    "отшлёпать": "отшлёпать",
    "отшлепать": "отшлёпать",
    "spank": "отшлёпать",
    "придушить": "придушить",
    "choke": "придушить",
    "засосать": "засосать",
    "hickey": "засосать",
    "сесть_на": "сесть_на",
    "сесть": "сесть_на",
    "lap": "сесть_на",
}

# Генерируем команды динамически
ALL_RP_COMMANDS = list(RP_ALIASES.keys())


async def _resolve_rp_target(message: Message) -> tuple[str | None, str | None]:
    """Возвращает (имя_цели, None) или (None, ошибка)."""
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        if target.is_bot:
            return None, "🤖 Нельзя использовать РП на боте."
        if target.id == message.from_user.id:
            return None, "🤔 На себе? Серьёзно?"
        return target.full_name, None

    parts = (message.text or "").split(None, 1)
    if len(parts) >= 2:
        arg = parts[1].strip().lstrip("@")
        if arg:
            # Попробуем найти юзера
            if arg.isdigit():
                u = await get_user(int(arg))
            else:
                u = await get_user_by_username(arg)
            if u:
                if u["user_id"] == message.from_user.id:
                    return None, "🤔 На себе? Серьёзно?"
                return u["full_name"], None
            # Если не нашли — используем как текст
            return arg, None

    return None, "💡 Укажи цель: ответь на сообщение или напиши @юзер."


@router.message(Command(*ALL_RP_COMMANDS, prefix=P))
async def rp_handler(message: Message, bot: Bot):
    text = (message.text or "").strip()
    if not text.startswith(P):
        return

    cmd = text.split()[0][len(P):].lower()

    action_key = RP_ALIASES.get(cmd)
    if not action_key or action_key not in RP_ACTIONS:
        return

    target_name, err = await _resolve_rp_target(message)
    if err:
        return await message.answer(err)

    action_verb, emoji, phrases = RP_ACTIONS[action_key]
    phrase = random.choice(phrases)
    sender = message.from_user.full_name

    caption = (
        f"{emoji} <b>{sender}</b> {action_verb} <b>{target_name}</b>\n"
        f"<i>{phrase}</i>"
    )

    # Пробуем отправить гифку
    gifs = [g for g in RP_GIFS.get(action_key, []) if g]
    if gifs:
        gif_url = random.choice(gifs)
        try:
            await message.answer_animation(
                animation=gif_url,
                caption=caption,
                parse_mode="HTML"
            )
            return
        except Exception:
            pass  # гифка не прошла — отправим просто текст

    await message.answer(caption, parse_mode="HTML")


# ── .рп — список доступных рп-команд ──────────────────────────────

@router.message(Command("рп", "rp", prefix=P))
async def cmd_rp_list(message: Message):
    lines = [
        "🎭 <b>РП-команды</b>\n"
        "Используй ответом на сообщение или с @юзером:\n"
    ]
    for key, (verb, emoji, _) in RP_ACTIONS.items():
        lines.append(f"  {emoji} <code>{P}{key}</code> — {verb}")

    await message.answer("\n".join(lines), parse_mode="HTML")
