from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import OWNER_ID, FRIEND_ID, BESTIE_ID
from db.database import (
    get_user, get_user_by_username, get_role,
    ROLES, ROLE_NAMES, ROLE_LABELS,
    get_top_messages, get_top_reputation, get_warn_log,
    get_marriage, get_rules, set_rules,
)

router = Router()
P = "."

ROLE_LABELS_STYLED = {
    "owner":  "👑 Создатель",
    "friend": "🌟 Коллега",
    "admin":  "⚙️ Администратор",
    "moder":  "🛡 Модератор",
    "user":   "☠️ Смертный",
}


def _build_profile_text(user_db: dict, marriage_info: str = "") -> str:
    uid       = user_db["user_id"]
    role_name = ROLE_NAMES.get(user_db["role"], "user")
    role_lbl  = ROLE_LABELS_STYLED.get(role_name, "☠️ Смертный")
    rep       = user_db.get("reputation", 0)
    msgs      = user_db.get("message_count", 0)
    warns     = user_db.get("warns", 0)
    bal       = user_db.get("balance", 0)

    if uid == OWNER_ID:
        header = "👑 ══════ СОЗДАТЕЛЬ ══════ 👑"
        flavor = "<i>Властелин этого чата. Не злите его.</i>"
    elif uid == FRIEND_ID:
        header = "🌟 ══════ КОЛЛЕГА ══════ 🌟"
        flavor = "<i>Свой среди своих.</i>"
    elif role_name == "admin":
        header = "⚙️ ══════ АДМИН ══════ ⚙️"
        flavor = "<i>Правая рука создателя. Уважай.</i>"
    elif role_name == "moder":
        header = "🛡 ══════ МОДЕРАТОР ══════ 🛡"
        flavor = "<i>Страж порядка. Не нарывайся.</i>"
    else:
        header = "☠️ Профиль смертного"
        flavor = None

    lines = [f"<b>{header}</b>"]
    if flavor:
        lines.append(flavor)
    lines.append("")
    lines.append(f"👤 <b>Имя:</b> {user_db['full_name']}")
    lines.append(f"🆔 <b>ID:</b> <code>{uid}</code>")
    lines.append(f"🎭 <b>Роль:</b> {role_lbl}")
    lines.append("")
    lines.append(f"💵 <b>Баланс:</b> {bal:,} монет")
    lines.append(f"✨ <b>Репутация:</b> {rep}")
    lines.append(f"💬 <b>Сообщений:</b> {msgs}")
    lines.append(f"⚠️ <b>Варны:</b> {warns}/3  {'🔴' * warns}{'⚪️' * (3 - warns)}")

    if marriage_info:
        lines.append(f"💍 <b>Брак:</b> {marriage_info}")

    if user_db.get("is_muted"):
        r = user_db.get("mute_reason") or "—"
        lines.append(f"🔇 <b>Мут:</b> Да  <i>({r})</i>")

    if user_db.get("is_banned"):
        r = user_db.get("ban_reason") or "—"
        lines.append(f"🚫 <b>Бан:</b> Да  <i>({r})</i>")

    return "\n".join(lines)


# ── /start ─────────────────────────────────────────────────────────

@router.message(Command("start", prefix="/."))
async def cmd_start(message: Message, user_db: dict):
    role_name = ROLE_NAMES.get(user_db["role"], "user")
    role_lbl  = ROLE_LABELS_STYLED.get(role_name, "☠️ Смертный")

    if user_db["user_id"] == OWNER_ID:
        greeting = "👑 Явился, хозяин."
    elif user_db["user_id"] == FRIEND_ID:
        greeting = f"🌟 О, коллега. Чего надо, <b>{message.from_user.full_name}</b>?"
    else:
        greeting = f"👋 Привет, <b>{message.from_user.full_name}</b>."

    await message.answer(
        f"{greeting}\n"
        f"Роль: {role_lbl}\n\n"
        f"Пингани меня или ответь на моё сообщение чтобы поговорить 🤖\n"
        f"Команды: {P}помощь",
        parse_mode="HTML"
    )


# ── .помощь ────────────────────────────────────────────────────────

@router.message(Command("помощь", "help", prefix=P))
async def cmd_help(message: Message, user_db: dict):
    lvl = user_db["role"]
    uid = user_db["user_id"]

    if uid == OWNER_ID:
        hello = "👑 <b>Слушаю, хозяин.</b> Доступные команды:\n"
    elif uid == FRIEND_ID:
        hello = "🌟 <b>Держи список, коллега.</b>\n"
    else:
        hello = "📋 <b>Команды бота</b> (префикс <code>.</code>)\n"

    lines = [hello]

    lines.append("╔═ 👤 <b>Профиль</b>")
    lines.append(f"║ {P}профиль — свой профиль")
    lines.append(f"║ {P}профиль @user — профиль другого")
    lines.append(f"║ {P}топ — топ по сообщениям")
    lines.append(f"║ {P}топреп — топ по репутации")
    lines.append("║")
    lines.append("╠═ 💰 <b>Экономика</b>")
    lines.append(f"║ {P}баланс — твои монеты")
    lines.append(f"║ {P}дейли — ежедневная награда")
    lines.append(f"║ {P}викли — еженедельная награда")
    lines.append(f"║ {P}работа — мини-игра (3/день)")
    lines.append(f"║ {P}передать [сумма] @user — перевод")
    lines.append(f"║ {P}топбаланс — богачи")
    lines.append("║")
    lines.append("╠═ 🎰 <b>Казино</b>")
    lines.append(f"║ {P}дэп [ставка] — слоты (мин. 100)")
    lines.append(f"║ {P}рулетка [ставка] [цвет/число]")
    lines.append(f"║ {P}коинфлип [ставка] [орёл/решка]")
    lines.append("║")
    lines.append("╠═ 🏪 <b>Магазин</b>")
    lines.append(f"║ {P}магазин — каталог")
    lines.append(f"║ {P}купить [товар]")
    lines.append("║")
    lines.append("╠═ 💍 <b>Браки</b>")
    lines.append(f"║ {P}брак @user — предложение")
    lines.append(f"║ {P}бракда / {P}бракнет — ответ")
    lines.append(f"║ {P}мойбрак — инфо")
    lines.append(f"║ {P}развод — расторжение")
    lines.append(f"║ {P}браки — список")
    lines.append("║")
    lines.append("╠═ 🔗 <b>Ссылки</b>")
    lines.append(f"║ {P}ссылки — все платформы")
    lines.append("║")
    lines.append("╠═ 🎭 <b>РП-команды</b>")
    lines.append(f"║ {P}рп — список РП-действий")
    lines.append(f"║ {P}обнять / {P}ударить / {P}кисс ...")
    lines.append("║")
    lines.append("╠═ 💬 <b>Репутация</b>")
    lines.append("║ + (ответом) — дать +1 репутацию")
    lines.append("║ респект/лайк/красавчик (ответом)")

    if lvl <= ROLES["moder"]:
        lines.append("║")
        lines.append("╠═ 🛡 <b>Модерация</b>")
        lines.append(f"║ {P}варн [время] [причина] — предупреждение (3 = мут)")
        lines.append(f"║ {P}варнлог — история варнов")
        lines.append(f"║ {P}снятьварн — сбросить варны")
        lines.append(f"║ {P}мут [время] [причина] — замутить (30м/2ч/1д)")
        lines.append(f"║ {P}размут — размутить")

    if lvl <= ROLES["admin"]:
        lines.append("║")
        lines.append("╠═ ⚙️ <b>Администрация</b>")
        lines.append(f"║ {P}бан [причина] — забанить и кикнуть")
        lines.append(f"║ {P}разбан — разбанить")
        lines.append(f"║ {P}роль ID роль — выдать роль")

    if lvl <= ROLES["owner"]:
        lines.append("║")
        lines.append("╠═ 👑 <b>Овнер</b>")
        lines.append(f"║ {P}персона — персоны ИИ")
        lines.append(f"║ {P}делперс — удалить персону")
        lines.append(f"║ {P}сброс — сбросить память ИИ")
        lines.append(f"║ {P}правила [текст] — правила")
        lines.append(f"║ {P}поженить @u1 @u2 — брак")
        lines.append(f"║ {P}развести @user — развод")

    lines.append("║")
    lines.append(f"║ 📜 {P}правила — правила чата")
    lines.append("╚═ 🤖 <b>ИИ:</b> упомяни меня или ответь на моё сообщение")
    lines.append(f"\n🖤 <code>{P}инфа</code> — узнать обо мне побольше")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ── .профиль ───────────────────────────────────────────────────────

@router.message(Command("профиль", "profile", prefix=P))
async def cmd_profile(message: Message, user_db: dict):
    target_db = None
    
    # Сначала проверяем аргумент команды (упоминание имеет приоритет над reply)
    parts = (message.text or "").split(None, 1)
    if len(parts) == 2:
        arg = parts[1].strip().lstrip("@")
        if arg.isdigit():
            target_db = await get_user(int(arg))
        else:
            target_db = await get_user_by_username(arg)
    
    # Если аргумента нет или юзер не найден - смотрим reply
    if target_db is None and message.reply_to_message and message.reply_to_message.from_user:
        ru = message.reply_to_message.from_user
        if not ru.is_bot:
            target_db = await get_user(ru.id)

    display_db = target_db if target_db else user_db

    # Инфо о браке
    marriage_info = ""
    chat_id = message.chat.id
    uid = display_db["user_id"]

    if message.chat.type in ("group", "supergroup"):
        m = await get_marriage(uid, chat_id)
        if m:
            partner_id = m["user2_id"] if m["user1_id"] == uid else m["user1_id"]
            partner = await get_user(partner_id)
            partner_name = partner["full_name"] if partner else f"id{partner_id}"
            marriage_info = f"💕 {partner_name}"
        elif uid == OWNER_ID:
            # Фолбэк если запись ещё не создалась
            marriage_info = "💕 Анха 🖤"

    # Юзеры могут смотреть чужой баланс и профиль (уже работает через target_db)

    await message.answer(
        _build_profile_text(display_db, marriage_info),
        parse_mode="HTML"
    )


# ── .топ ───────────────────────────────────────────────────────────

@router.message(Command("топ", "top", prefix=P))
async def cmd_top(message: Message):
    rows = await get_top_messages(10)
    if not rows:
        return await message.answer("📊 Статистика пуста — пишите больше!")

    lines = [
        "📊 <b>Топ активности чата</b>\n"
        "Кто тут больше всех болтает:\n"
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(rows, 1):
        name = u.get("full_name") or u.get("username") or f"id{u['user_id']}"
        icon = medals[i - 1] if i <= 3 else f"<code>{i}.</code>"
        lines.append(f"  {icon} {name} — <b>{u.get('message_count', 0)}</b> сообщ.")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── .топреп ────────────────────────────────────────────────────────

@router.message(Command("топреп", "toprep", prefix=P))
async def cmd_toprep(message: Message):
    rows = await get_top_reputation(10)
    if not rows:
        return await message.answer("✨ Репутация ещё не накоплена — ставьте + в ответ на сообщения!")

    lines = [
        "✨ <b>Топ репутации</b>\n"
        "Самые уважаемые жители чата:\n"
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(rows, 1):
        name = u.get("full_name") or u.get("username") or f"id{u['user_id']}"
        icon = medals[i - 1] if i <= 3 else f"<code>{i}.</code>"
        lines.append(f"  {icon} {name} — <b>{u.get('reputation', 0)}</b> ✨")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── .инфа ──────────────────────────────────────────────────────────

@router.message(Command("инфа", "info", "about", prefix=P))
async def cmd_info(message: Message):
    await message.answer(
        "🖤 <b>Кто я такая?</b>\n\n"
        "Меня зовут <b>Анха</b>. Я демоница, которая застряла в мире людей "
        "и теперь тусуюсь в этом чатике. Да, я девушка Анкха. Завидуйте молча.\n\n"
        "Моя кожа на лице белая как снег, а ниже шеи — чёрная как уголь. "
        "Волосы белые, глаза без зрачков — да, я знаю, это жутко. "
        "Клык торчит? Это не баг, это фича.\n\n"
        "╔══════════════════════╗\n"
        "  ⚙️ <b>ЧТО Я УМЕЮ</b>\n"
        "╚══════════════════════╝\n\n"
        "🤖 <b>ИИ-чат</b> — пингни меня или ответь на моё сообщение, "
        "и я тебе отвечу. Если заслужишь.\n\n"
        "💰 <b>Экономика</b> — монеты за активность, ежедневные награды, "
        "казино (дэп, рулетка, коинфлип) и магазин с товарами.\n\n"
        "💍 <b>Браки</b> — можно предложить руку и сердце кому-нибудь. "
        "Да, я знаю, это смешно. Но людям нравится.\n\n"
        "✨ <b>Репутация</b> — отвечай на сообщения словами типа "
        "«респект», «красавчик», «+» и другими.\n\n"
        "🛡 <b>Модерация</b> — варны, муты, баны. "
        "Кому-то же надо следить за порядком.\n\n"
        "📺 <b>YouTube</b> — я слежу за каналом хозяина "
        "и скидываю новые видео в Telegram-канал.\n\n"
        "🖤 <i>Не путайте мою дерзость с враждебностью. "
        "Я просто... такая.</i>\n\n"
        f"📋 Все команды: <code>{P}помощь</code>",
        parse_mode="HTML"
    )


# ── .правила ───────────────────────────────────────────────────────

@router.message(Command("правила", "rules", prefix=P))
async def cmd_rules(message: Message, user_db: dict):
    chat_id = message.chat.id
    text = (message.text or "")

    # Если есть текст после команды — установка правил (только овнер)
    parts = text.split(None, 1)
    if len(parts) >= 2 and parts[1].strip():
        if user_db["user_id"] != OWNER_ID:
            return await message.answer("⛔ Только создатель может менять правила.")
        new_rules = parts[1].strip()
        await set_rules(chat_id, new_rules)
        return await message.answer(
            f"✅ Правила обновлены!\n\n"
            f"📜 <b>Правила чата:</b>\n{new_rules}",
            parse_mode="HTML"
        )

    # Просмотр правил
    rules = await get_rules(chat_id)
    if not rules:
        return await message.answer("📜 Правила ещё не установлены.")

    await message.answer(
        f"📜 <b>Правила чата:</b>\n\n{rules}",
        parse_mode="HTML"
    )
