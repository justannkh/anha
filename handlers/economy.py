import random
import time
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import (
    DAILY_REWARD, DAILY_REWARD_STREAK,
    CASINO_MAX_BET,
    SHOP_BOOSTI_URL, LINK_BOOSTI,
    OWNER_ID, FRIEND_ID, BESTIE_ID,
)
from db.database import (
    get_user, get_user_by_username,
    get_balance, update_balance, safe_spend,
    get_daily_info, set_daily_info,
    get_weekly_info, set_weekly_info,
    get_work_info, set_work_info,
    get_top_balance, add_purchase,
    has_purchased, has_active_vip, has_active_premium, has_active_elite,
    get_user_status,
)

router = Router()
P = "."

# ── Рейт-лимит казино: макс 10 ставок за 60 секунд ───────────────
CASINO_RATE_MAX = 10
CASINO_RATE_WINDOW = 60

_casino_buckets: dict[int, list[float]] = {}


def _check_casino_rate(user_id: int) -> tuple[bool, int]:
    now = time.time()
    cutoff = now - CASINO_RATE_WINDOW
    if user_id not in _casino_buckets:
        _casino_buckets[user_id] = []
    _casino_buckets[user_id] = [t for t in _casino_buckets[user_id] if t > cutoff]
    if len(_casino_buckets[user_id]) >= CASINO_RATE_MAX:
        oldest = _casino_buckets[user_id][0]
        wait = int(oldest + CASINO_RATE_WINDOW - now) + 1
        return False, max(wait, 1)
    _casino_buckets[user_id].append(now)
    return True, 0

# ══════════════════════════════════════════════════════════════════
#  МАГАЗИН
# ══════════════════════════════════════════════════════════════════

SHOP_ITEMS = {
    "vip": {
        "name": "💎 VIP-статус",
        "desc": "x2 к наградам на 30 дней. Золотой профиль. Авто-активация.",
        "price": 30000,
        "repeatable": True,
    },
    "premium": {
        "name": "⭐ Premium-статус",
        "desc": "x1.5 к наградам на 14 дней. Серебряный профиль. Авто-активация.",
        "price": 15000,
        "repeatable": True,
    },
    "elite": {
        "name": "🔥 Elite-статус",
        "desc": "x1.25 к наградам на 7 дней. Бронзовый профиль. Авто-активация.",
        "price": 5000,
        "repeatable": True,
    },
    "boosti_sub": {
        "name": "🎁 Подписка Boosty",
        "desc": "Подписка «Базовый минимум» на Boosty на 1 месяц.",
        "price": 150000,
        "repeatable": False,
    },
    "custom_title": {
        "name": "🏷 Кастомный титул",
        "desc": "Уникальный титул в профиле. Пишите администрации.",
        "price": 50000,
        "repeatable": False,
    },
    "rep_boost": {
        "name": "⚡ Буст репутации",
        "desc": "+50 к репутации мгновенно.",
        "price": 35000,
        "repeatable": False,
    },
    "lucky_box": {
        "name": "🎲 Ящик удачи",
        "desc": "Случайный приз от 500 до 5000 монет.",
        "price": 3000,
        "repeatable": True,
    },
    "mega_box": {
        "name": "🎁 Мега-ящик",
        "desc": "Случайный приз от 5000 до 30000 монет!",
        "price": 15000,
        "repeatable": True,
    },
}


# ══════════════════════════════════════════════════════════════════
#  СЛОТ-МАШИНА (казино)
# ══════════════════════════════════════════════════════════════════

SLOT_EMOJIS = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣", "🔔"]

SLOT_PAYOUTS = {
    ("7️⃣", "7️⃣", "7️⃣"): 10,    # джекпот x10
    ("💎", "💎", "💎"): 7,     # x7
    ("🍇", "🍇", "🍇"): 5,     # x5
    ("🔔", "🔔", "🔔"): 4,     # x4
    ("🍊", "🍊", "🍊"): 3,     # x3
    ("🍋", "🍋", "🍋"): 3,     # x3
    ("🍒", "🍒", "🍒"): 2,     # x2
}


def _spin_slots() -> tuple[list[str], float]:
    """Крутит барабаны. Возвращает (символы, множитель)."""
    reels = [random.choice(SLOT_EMOJIS) for _ in range(3)]
    combo = tuple(reels)

    # Точное совпадение
    if combo in SLOT_PAYOUTS:
        return reels, SLOT_PAYOUTS[combo]

    # Два из трёх
    if reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        return reels, 1.5

    return reels, 0


# ── .баланс ───────────────────────────────────────────────────────

@router.message(Command("баланс", "balance", "bal", prefix=P))
async def cmd_balance(message: Message, user_db: dict):
    bal = user_db.get("balance", 0)
    streak = user_db.get("daily_streak", 0)
    uid = message.from_user.id

    is_prime = uid in (OWNER_ID, FRIEND_ID, BESTIE_ID)
    status_name, multiplier = await get_user_status(uid)

    if status_name:
        status_line = f"\n{status_name} (x{multiplier} к наградам)"
    elif is_prime:
        status_line = "\n👑 Статус: <b>Прайм</b> (x1.5 к наградам)"
    else:
        status_line = ""

    await message.answer(
        f"💰 <b>Кошелёк</b>\n\n"
        f"👤 {message.from_user.full_name}\n"
        f"💵 Баланс: <b>{bal:,}</b> монет\n"
        f"🔥 Серия ежедневных: <b>{streak}</b> дн.{status_line}",
        parse_mode="HTML"
    )


# ── .ежедневная ───────────────────────────────────────────────────

@router.message(Command("ежедневная", "дейли", "daily", prefix=P))
async def cmd_daily(message: Message, user_db: dict):
    user_id = message.from_user.id
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    last_daily, streak = await get_daily_info(user_id)

    if last_daily == today_str:
        return await message.answer(
            "⏰ Ты уже забирал ежедневную награду сегодня!\n"
            "Приходи завтра 🌅"
        )

    # Проверяем серию
    yesterday_str = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    if last_daily == yesterday_str:
        streak += 1
    else:
        streak = 1

    bonus = DAILY_REWARD_STREAK * (streak - 1)
    total = DAILY_REWARD + bonus

    # Статусы: VIP > Premium > Elite > Прайм
    is_prime = user_id in (OWNER_ID, FRIEND_ID, BESTIE_ID)
    status_name, multiplier = await get_user_status(user_id)

    if status_name:
        total = int(total * multiplier)
        status_text = f"\n{status_name} <b>бонус: x{multiplier}!</b>"
    elif is_prime:
        total = int(total * 1.5)
        status_text = "\n👑 <b>Прайм-бонус: x1.5!</b>"
    else:
        status_text = ""

    # Сначала помечаем дату (защита от двойного получения при race condition)
    await set_daily_info(user_id, today_str, streak)
    new_bal = await update_balance(user_id, total, "daily", f"Серия: {streak}")

    streak_text = ""
    if streak > 1:
        streak_text = f"\n🔥 Серия: <b>{streak}</b> дней (+{bonus} бонус!)"

    await message.answer(
        f"╔══════════════════════╗\n"
        f"  🎁 <b>ЕЖЕДНЕВНАЯ НАГРАДА</b>\n"
        f"╚══════════════════════╝\n\n"
        f"💵 +<b>{total}</b> монет{streak_text}{status_text}\n"
        f"💰 Баланс: <b>{new_bal:,}</b>",
        parse_mode="HTML"
    )


# ── .еженедельная ─────────────────────────────────────────────────

WEEKLY_REWARD = 3000

@router.message(Command("еженедельная", "викли", "weekly", prefix=P))
async def cmd_weekly(message: Message, user_db: dict):
    user_id = message.from_user.id
    # Номер недели в году
    now = datetime.utcnow()
    week_str = f"{now.year}-W{now.isocalendar()[1]}"
    last_weekly = await get_weekly_info(user_id)

    if last_weekly == week_str:
        return await message.answer(
            "⏰ Ты уже забирал еженедельную награду!\n"
            "Следующая — на следующей неделе 📅"
        )

    total = WEEKLY_REWARD
    is_prime = user_id in (OWNER_ID, FRIEND_ID, BESTIE_ID)
    status_name, multiplier = await get_user_status(user_id)

    if status_name:
        total = int(total * multiplier)
        status_text = f"\n{status_name} <b>бонус: x{multiplier}!</b>"
    elif is_prime:
        total = int(total * 1.5)
        status_text = "\n👑 <b>Прайм-бонус: x1.5!</b>"
    else:
        status_text = ""

    await set_weekly_info(user_id, week_str)
    new_bal = await update_balance(user_id, total, "weekly", "Еженедельная")

    await message.answer(
        f"╔══════════════════════╗\n"
        f"  📦 <b>ЕЖЕНЕДЕЛЬНАЯ НАГРАДА</b>\n"
        f"╚══════════════════════╝\n\n"
        f"💵 +<b>{total}</b> монет{status_text}\n"
        f"💰 Баланс: <b>{new_bal:,}</b>",
        parse_mode="HTML"
    )


# ── .работа ────────────────────────────────────────────────────────

WORK_MAX_PER_DAY = 3

# ══════════════════════════════════════════════════════════════════
#  МИНИ-ИГРА «РАБОТА» — случайные приключения с рандомным исходом
#  Юзер пишет .работа → бот кидает кубик → история разворачивается
#  Никаких вопросов — чистый рандом и нарратив
# ══════════════════════════════════════════════════════════════════

WORK_SCENARIOS = [
    {
        "name": "🏦 Ограбление банка",
        "start": "Ты надел маску и ворвался в банк...",
        "outcomes": [
            (35, "💰 Хранилище было открыто! Набил карманы и сбежал.", 1500, 3000),
            (25, "🚔 Сигнализация, но успел схватить пару пачек.", 600, 1200),
            (20, "😰 Охранник заметил, пришлось бежать с мелочью.", 200, 500),
            (20, "🚨 Полиция поймала. Откупился взяткой.", -300, -100),
        ],
    },
    {
        "name": "🎮 Турнир по киберспорту",
        "start": "Ты зарегистрировался на онлайн-турнир...",
        "outcomes": [
            (20, "🏆 Первое место! Призовой фонд твой!", 2000, 4000),
            (30, "🥈 Дошёл до финала. Утешительный приз.", 800, 1500),
            (30, "😤 Вылетел в четвертьфинале.", 300, 700),
            (20, "💀 Проиграл первый матч. Бывает...", 50, 200),
        ],
    },
    {
        "name": "🏎 Уличные гонки",
        "start": "Тебя позвали на нелегальные ночные гонки...",
        "outcomes": [
            (25, "🏁 Финишировал первым! Забрал ставки!", 1800, 3500),
            (25, "🥈 Второе место. Неплохо.", 700, 1300),
            (25, "🔧 Машина заглохла на полпути.", 100, 400),
            (25, "💥 Вписался в забор. Ремонт дороже.", -200, 0),
        ],
    },
    {
        "name": "💎 Кладоискатель",
        "start": "Ты нашёл старую карту сокровищ...",
        "outcomes": [
            (15, "👑 Нашёл сундук с золотом! Джекпот!", 2500, 5000),
            (30, "💍 Нашёл старинные монеты.", 800, 1600),
            (35, "🪨 Выкопал... камень.", 150, 400),
            (20, "🐍 Змея! Убежал без находок.", 0, 100),
        ],
    },
    {
        "name": "🎰 Подпольное казино",
        "start": "Тебя привели в тайный покерный клуб...",
        "outcomes": [
            (20, "🃏 Роял-флеш! Забрал весь банк!", 2000, 4500),
            (25, "😎 Выиграл пару раздач.", 800, 1500),
            (30, "😐 Остался при своих.", 200, 500),
            (25, "😱 Проиграл всё. Еле выбрался.", -150, 50),
        ],
    },
    {
        "name": "📦 Контрабанда",
        "start": "Друг попросил перевезти подозрительную коробку...",
        "outcomes": [
            (30, "✈️ Доставил без проблем. Щедрая оплата.", 1200, 2500),
            (25, "🤔 Заплатили меньше обещанного.", 500, 900),
            (25, "🚔 Почти попался, выбросил груз.", 100, 300),
            (20, "👮 Полиция остановила. Откупился.", -250, 0),
        ],
    },
    {
        "name": "🎵 Уличный концерт",
        "start": "Ты взял гитару и пошёл играть в переходе...",
        "outcomes": [
            (25, "🎶 Толпа! Кидали деньги горстями!", 1000, 2000),
            (30, "👏 Несколько человек оценили.", 500, 1000),
            (30, "😐 Прошли мимо. Пара монет.", 150, 400),
            (15, "🍅 Кинули помидор. Не артист.", 0, 100),
        ],
    },
    {
        "name": "🔧 Ремонт за бабки",
        "start": "Сосед попросил починить компьютер...",
        "outcomes": [
            (30, "💻 Починил за 5 минут! Шок и чаевые!", 800, 1600),
            (35, "🔨 Провозился весь вечер.", 400, 800),
            (20, "💀 Удалил все данные. Сосед злой.", 50, 200),
            (15, "🔥 Компьютер задымился.", -100, 50),
        ],
    },
    {
        "name": "🐕 Выгул собак",
        "start": "Выгуливаешь собак богачей...",
        "outcomes": [
            (30, "🐩 Все послушные. Хозяйка дала чаевые!", 900, 1800),
            (30, "🐶 Одна сбежала, но поймал.", 400, 800),
            (25, "🦴 Собаки перегрызли поводок.", 100, 350),
            (15, "💩 Собака укусила прохожего. Штраф.", -200, 0),
        ],
    },
    {
        "name": "🎲 Напёрсточник",
        "start": "Ты встал с напёрстками у вокзала...",
        "outcomes": [
            (25, "🤑 Лохи попались! Обчистил!", 1300, 2800),
            (25, "😏 Пара клиентов клюнули.", 600, 1200),
            (25, "🤨 Никто не ведётся.", 100, 300),
            (25, "👊 Клиент не лох. Пришлось бежать.", -150, 50),
        ],
    },
]


@router.message(Command("работа", "work", "job", prefix=P))
async def cmd_work(message: Message, user_db: dict):
    user_id = message.from_user.id
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    last_work, work_count = await get_work_info(user_id)

    if last_work != today_str:
        work_count = 0

    if work_count >= WORK_MAX_PER_DAY:
        return await message.answer(
            f"😮‍💨 Ты уже отработал {WORK_MAX_PER_DAY} раза сегодня.\n"
            "Отдохни, завтра продолжишь!"
        )

    # Выбираем случайный сценарий
    scenario = random.choice(WORK_SCENARIOS)

    # Кидаем кубик — выбираем исход по весам
    roll = random.randint(1, 100)
    cumulative = 0
    chosen_outcome = scenario["outcomes"][-1]  # фолбэк
    for weight, desc, min_r, max_r in scenario["outcomes"]:
        cumulative += weight
        if roll <= cumulative:
            chosen_outcome = (weight, desc, min_r, max_r)
            break

    _, outcome_desc, min_reward, max_reward = chosen_outcome
    reward = random.randint(min(min_reward, max_reward), max(min_reward, max_reward))

    # Записываем работу
    new_count = work_count + 1
    await set_work_info(user_id, today_str, new_count)

    if reward > 0:
        new_bal = await update_balance(user_id, reward, "work", scenario["name"])
        reward_line = f"💰 +<b>{reward}</b> монет"
    elif reward < 0:
        # Не уходим в минус
        bal = await get_balance(user_id)
        loss = min(abs(reward), bal)
        if loss > 0:
            new_bal = await update_balance(user_id, -loss, "work_loss", scenario["name"])
        else:
            new_bal = bal
        reward_line = f"💸 <b>{reward}</b> монет" if reward < 0 else "💸 <b>0</b> монет"
    else:
        new_bal = await get_balance(user_id)
        reward_line = "💸 <b>0</b> монет"

    await message.answer(
        f"╔══════════════════════╗\n"
        f"  🔨 <b>{scenario['name']}</b>\n"
        f"╚══════════════════════╝\n\n"
        f"<i>{scenario['start']}</i>\n\n"
        f"{outcome_desc}\n\n"
        f"{reward_line}\n"
        f"💵 Баланс: <b>{new_bal:,}</b>\n"
        f"📊 Работ сегодня: {new_count}/{WORK_MAX_PER_DAY}",
        parse_mode="HTML"
    )


# Экспорт для совместимости (работа больше не нужна active_jobs)
def has_active_job(user_id: int) -> bool:
    return False


# ── .дэп / .казино / .слот ────────────────────────────────────────

DEP_MIN_BET = 100  # минимум для дэпа

@router.message(Command("дэп", "dep", "казино", "слот", "slot", "casino", prefix=P))
async def cmd_casino(message: Message, user_db: dict):
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer(
            f"🎰 <b>Дэп — Слот-машина</b>\n\n"
            f"Формат: <code>{P}дэп [ставка]</code>\n"
            f"Ставка: от {DEP_MIN_BET} до {CASINO_MAX_BET} монет\n\n"
            f"<b>Выплаты:</b>\n"
            f"  7️⃣7️⃣7️⃣ — x10\n"
            f"  💎💎💎 — x7\n"
            f"  🍇🍇🍇 — x5\n"
            f"  🔔🔔🔔 — x4\n"
            f"  🍊🍊🍊 / 🍋🍋🍋 — x3\n"
            f"  🍒🍒🍒 — x2\n"
            f"  Два совпадения — x1.5\n",
            parse_mode="HTML"
        )

    try:
        bet = int(parts[1])
    except ValueError:
        return await message.answer("❌ Укажи ставку числом.")

    if bet < DEP_MIN_BET:
        return await message.answer(f"❌ Минимальная ставка: <b>{DEP_MIN_BET}</b> монет.", parse_mode="HTML")
    if bet > CASINO_MAX_BET:
        return await message.answer(f"❌ Максимальная ставка: <b>{CASINO_MAX_BET}</b> монет.", parse_mode="HTML")

    # Рейт-лимит казино
    allowed, wait_sec = _check_casino_rate(message.from_user.id)
    if not allowed:
        return await message.answer(
            f"🎰 Полегче, азартный! Макс. {CASINO_RATE_MAX} ставок в минуту.\n"
            f"⏳ Подожди <b>{wait_sec}</b> сек.",
            parse_mode="HTML"
        )

    # Атомарное списание — защита от минусового баланса
    after_spend = await safe_spend(message.from_user.id, bet, "casino_bet", "Ставка слот")
    if after_spend is None:
        bal = await get_balance(message.from_user.id)
        return await message.answer(
            f"💸 Недостаточно монет!\n"
            f"Твой баланс: <b>{bal:,}</b>, а ставка: <b>{bet:,}</b>",
            parse_mode="HTML"
        )

    # Крутим!
    reels, multiplier = _spin_slots()
    display = " | ".join(reels)

    if multiplier > 0:
        winnings = int(bet * multiplier)
        new_bal = await update_balance(message.from_user.id, winnings, "casino_win", f"x{multiplier}")

        if multiplier >= 7:
            result_text = "🎊🎊🎊 <b>ДЖЕКПОТ!!!</b> 🎊🎊🎊"
        elif multiplier >= 3:
            result_text = "🎉 <b>КРУПНЫЙ ВЫИГРЫШ!</b>"
        elif multiplier >= 2:
            result_text = "✨ <b>Выигрыш!</b>"
        else:
            result_text = "👍 <b>Мелкий выигрыш</b>"

        await message.answer(
            f"🎰 <b>СЛОТ-МАШИНА</b>\n\n"
            f"╔═══════════════╗\n"
            f"  [ {display} ]\n"
            f"╚═══════════════╝\n\n"
            f"{result_text}\n"
            f"💰 Ставка: {bet:,} → Выигрыш: <b>{winnings:,}</b> (x{multiplier})\n"
            f"💵 Баланс: <b>{new_bal:,}</b>",
            parse_mode="HTML"
        )
    else:
        new_bal = after_spend  # уже списано через safe_spend
        await message.answer(
            f"🎰 <b>СЛОТ-МАШИНА</b>\n\n"
            f"╔═══════════════╗\n"
            f"  [ {display} ]\n"
            f"╚═══════════════╝\n\n"
            f"😢 <b>Не повезло...</b>\n"
            f"💸 Потеряно: <b>{bet:,}</b> монет\n"
            f"💵 Баланс: <b>{new_bal:,}</b>",
            parse_mode="HTML"
        )


# ── .рулетка (числовая) ──────────────────────────────────────────

ROULETTE_MIN_BET = 50

@router.message(Command("рулетка", "roulette", prefix=P))
async def cmd_roulette(message: Message, user_db: dict):
    parts = (message.text or "").split()
    if len(parts) < 3:
        return await message.answer(
            f"🎯 <b>Рулетка</b>\n\n"
            f"Формат: <code>{P}рулетка [ставка] [красное/чёрное/число]</code>\n\n"
            f"Ставка: от {ROULETTE_MIN_BET} до {CASINO_MAX_BET} монет\n"
            f"<b>Цвета:</b> красное / чёрное — x2\n"
            f"<b>Число:</b> от 0 до 36 — x36",
            parse_mode="HTML"
        )

    try:
        bet = int(parts[1])
    except ValueError:
        return await message.answer("❌ Укажи ставку числом.")

    if bet < ROULETTE_MIN_BET or bet > CASINO_MAX_BET:
        return await message.answer(f"❌ Ставка: от {ROULETTE_MIN_BET} до {CASINO_MAX_BET}.")

    # Рейт-лимит казино
    allowed, wait_sec = _check_casino_rate(message.from_user.id)
    if not allowed:
        return await message.answer(f"🎯 Полегче! ⏳ Подожди <b>{wait_sec}</b> сек.", parse_mode="HTML")

    choice = parts[2].lower()
    result_num = random.randint(0, 36)

    # Красные числа в рулетке
    red_numbers = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    result_color = "🔴" if result_num in red_numbers else ("⚫" if result_num > 0 else "🟢")
    result_color_name = "красное" if result_num in red_numbers else ("чёрное" if result_num > 0 else "зеро")

    won = False
    multiplier = 0

    if choice in ("красное", "красный", "red", "к"):
        won = result_num in red_numbers
        multiplier = 2
    elif choice in ("чёрное", "чёрный", "черное", "black", "ч"):
        won = result_num not in red_numbers and result_num > 0
        multiplier = 2
    elif choice.isdigit():
        num = int(choice)
        if 0 <= num <= 36:
            won = result_num == num
            multiplier = 36
        else:
            return await message.answer("❌ Число от 0 до 36.")
    else:
        return await message.answer("❌ Укажи: красное, чёрное или число 0-36.")

    # Атомарное списание
    after_spend = await safe_spend(message.from_user.id, bet, "roulette_bet", "Ставка рулетка")
    if after_spend is None:
        bal = await get_balance(message.from_user.id)
        return await message.answer(f"💸 Недостаточно монет! Баланс: <b>{bal:,}</b>", parse_mode="HTML")

    if won:
        winnings = bet * multiplier
        new_bal = await update_balance(message.from_user.id, winnings, "roulette_win", f"x{multiplier}")
        await message.answer(
            f"🎯 <b>РУЛЕТКА</b>\n\n"
            f"Шарик упал на: {result_color} <b>{result_num}</b> ({result_color_name})\n\n"
            f"🎉 <b>Выигрыш!</b> x{multiplier}\n"
            f"💰 +<b>{winnings:,}</b> монет\n"
            f"💵 Баланс: <b>{new_bal:,}</b>",
            parse_mode="HTML"
        )
    else:
        new_bal = after_spend  # уже списано
        await message.answer(
            f"🎯 <b>РУЛЕТКА</b>\n\n"
            f"Шарик упал на: {result_color} <b>{result_num}</b> ({result_color_name})\n\n"
            f"😢 <b>Не повезло...</b>\n"
            f"💸 -{bet:,} монет\n"
            f"💵 Баланс: <b>{new_bal:,}</b>",
            parse_mode="HTML"
        )


# ── .коинфлип ─────────────────────────────────────────────────────

COINFLIP_MIN_BET = 25

@router.message(Command("коинфлип", "coinflip", "монетка", prefix=P))
async def cmd_coinflip(message: Message, user_db: dict):
    parts = (message.text or "").split()
    if len(parts) < 3:
        return await message.answer(
            f"🪙 <b>Коинфлип</b>\n\n"
            f"Формат: <code>{P}коинфлип [ставка] [орёл/решка]</code>\n"
            f"Ставка: от {COINFLIP_MIN_BET} до {CASINO_MAX_BET}\n"
            f"Выигрыш: x2",
            parse_mode="HTML"
        )

    try:
        bet = int(parts[1])
    except ValueError:
        return await message.answer("❌ Укажи ставку числом.")

    if bet < COINFLIP_MIN_BET or bet > CASINO_MAX_BET:
        return await message.answer(f"❌ Ставка: от {COINFLIP_MIN_BET} до {CASINO_MAX_BET}.")

    # Рейт-лимит казино
    allowed, wait_sec = _check_casino_rate(message.from_user.id)
    if not allowed:
        return await message.answer(f"🪙 Полегче! ⏳ Подожди <b>{wait_sec}</b> сек.", parse_mode="HTML")

    choice = parts[2].lower()
    if choice not in ("орёл", "орел", "решка", "о", "р", "heads", "tails"):
        return await message.answer("❌ Укажи: орёл или решка.")

    # Атомарное списание
    after_spend = await safe_spend(message.from_user.id, bet, "coinflip_bet", "Ставка коинфлип")
    if after_spend is None:
        bal = await get_balance(message.from_user.id)
        return await message.answer(f"💸 Недостаточно монет! Баланс: <b>{bal:,}</b>", parse_mode="HTML")

    is_heads_choice = choice in ("орёл", "орел", "о", "heads")
    is_heads_result = random.random() < 0.5

    result_text = "🦅 Орёл" if is_heads_result else "👑 Решка"
    won = is_heads_choice == is_heads_result

    if won:
        winnings = bet * 2
        new_bal = await update_balance(message.from_user.id, winnings, "coinflip_win", "x2")
        await message.answer(
            f"🪙 <b>КОИНФЛИП</b>\n\n"
            f"Результат: <b>{result_text}</b>\n\n"
            f"🎉 <b>Угадал!</b>\n"
            f"💰 +<b>{bet:,}</b> монет\n"
            f"💵 Баланс: <b>{new_bal:,}</b>",
            parse_mode="HTML"
        )
    else:
        new_bal = after_spend  # уже списано
        await message.answer(
            f"🪙 <b>КОИНФЛИП</b>\n\n"
            f"Результат: <b>{result_text}</b>\n\n"
            f"😢 <b>Мимо...</b>\n"
            f"💸 -{bet:,} монет\n"
            f"💵 Баланс: <b>{new_bal:,}</b>",
            parse_mode="HTML"
        )


# ── .передать ─────────────────────────────────────────────────────

@router.message(Command("передать", "transfer", "pay", prefix=P))
async def cmd_transfer(message: Message, user_db: dict):
    parts = (message.text or "").split()
    if len(parts) < 3:
        return await message.answer(
            f"💸 <b>Перевод монет</b>\n\n"
            f"Формат: <code>{P}передать [кол-во] @юзер</code>",
            parse_mode="HTML"
        )

    try:
        amount = int(parts[1])
    except ValueError:
        return await message.answer("❌ Укажи сумму числом.")

    if amount <= 0:
        return await message.answer("❌ Сумма должна быть больше 0.")

    # Поиск получателя
    target_db = None
    if message.reply_to_message and message.reply_to_message.from_user:
        ru = message.reply_to_message.from_user
        if not ru.is_bot:
            target_db = await get_user(ru.id)
    else:
        arg = parts[2].lstrip("@")
        if arg.isdigit():
            target_db = await get_user(int(arg))
        else:
            target_db = await get_user_by_username(arg)

    if not target_db:
        return await message.answer("❓ Юзер не найден.")
    if target_db["user_id"] == message.from_user.id:
        return await message.answer("😅 Нельзя переводить самому себе.")

    # Атомарное списание
    after_spend = await safe_spend(message.from_user.id, amount, "transfer_out", f"→ {target_db['full_name']}")
    if after_spend is None:
        bal = await get_balance(message.from_user.id)
        return await message.answer(f"💸 Недостаточно монет! Баланс: <b>{bal:,}</b>", parse_mode="HTML")

    await update_balance(target_db["user_id"], amount, "transfer_in", f"← {message.from_user.full_name}")

    await message.answer(
        f"💸 <b>Перевод выполнен!</b>\n\n"
        f"👤 {message.from_user.full_name} → {target_db['full_name']}\n"
        f"💰 Сумма: <b>{amount:,}</b> монет\n"
        f"💵 Твой баланс: <b>{after_spend:,}</b>",
        parse_mode="HTML"
    )


# ── .топбаланс ────────────────────────────────────────────────────

@router.message(Command("топбаланс", "topbal", "richest", prefix=P))
async def cmd_topbalance(message: Message):
    rows = await get_top_balance(10)
    if not rows:
        return await message.answer("💰 Пока все на нуле — экономика ещё не стартовала!")

    lines = [
        "💰 <b>Богатейшие жители чата</b>\n"
        "Кто сколько накопил:\n"
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(rows, 1):
        name = u.get("full_name") or u.get("username") or f"id{u['user_id']}"
        icon = medals[i - 1] if i <= 3 else f"<code>{i}.</code>"
        lines.append(f"  {icon} {name} — <b>{u.get('balance', 0):,}</b> 💵")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── .магазин ──────────────────────────────────────────────────────

@router.message(Command("магазин", "shop", "store", prefix=P))
async def cmd_shop(message: Message, user_db: dict):
    bal = user_db.get("balance", 0)
    lines = [
        f"🏪 <b>Магазин</b>\n"
        f"💵 Твой баланс: <b>{bal:,}</b> монет\n"
    ]
    for key, item in SHOP_ITEMS.items():
        affordable = "✅" if bal >= item["price"] else "❌"
        lines.append(
            f"  {affordable} <b>{item['name']}</b> — {item['price']:,} монет\n"
            f"      <i>{item['desc']}</i>\n"
            f"      Купить: <code>{P}купить {key}</code>\n"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── .купить ───────────────────────────────────────────────────────

@router.message(Command("купить", "buy", prefix=P))
async def cmd_buy(message: Message, user_db: dict):
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer(
            f"🏪 Формат: <code>{P}купить [товар]</code>\n"
            f"Список товаров: <code>{P}магазин</code>",
            parse_mode="HTML"
        )

    item_key = parts[1].lower()
    if item_key not in SHOP_ITEMS:
        return await message.answer(
            f"❌ Товар <b>{item_key}</b> не найден.\n"
            f"Смотри каталог: <code>{P}магазин</code>",
            parse_mode="HTML"
        )

    item = SHOP_ITEMS[item_key]

    # Проверка повторной покупки
    if not item.get("repeatable", False):
        already = await has_purchased(message.from_user.id, item_key)
        if already:
            return await message.answer(
                f"❌ Ты уже покупал <b>{item['name']}</b>.\n"
                f"Этот товар можно купить только один раз.",
                parse_mode="HTML"
            )
    elif item_key == "vip":
        if await has_active_vip(message.from_user.id):
            return await message.answer(
                "💎 У тебя уже есть активный VIP!\n"
                "Дождись окончания срока (30 дней).",
            )
    elif item_key == "premium":
        if await has_active_vip(message.from_user.id):
            return await message.answer(
                "💎 У тебя уже VIP (x2) — Premium (x1.5) слабее.\n"
                "Не трать монеты зря!",
            )
        if await has_active_premium(message.from_user.id):
            return await message.answer(
                "⭐ У тебя уже есть активный Premium!\n"
                "Дождись окончания срока (14 дней).",
            )
    elif item_key == "elite":
        if await has_active_vip(message.from_user.id):
            return await message.answer(
                "💎 У тебя уже VIP (x2) — Elite (x1.25) слабее.\n"
                "Не трать монеты зря!",
            )
        if await has_active_premium(message.from_user.id):
            return await message.answer(
                "⭐ У тебя уже Premium (x1.5) — Elite (x1.25) слабее.\n"
                "Не трать монеты зря!",
            )
        if await has_active_elite(message.from_user.id):
            return await message.answer(
                "🔥 У тебя уже есть активный Elite!\n"
                "Дождись окончания срока (7 дней).",
            )

    # Обработка спецтоваров
    extra_msg = ""

    if item_key == "lucky_box":
        after_spend = await safe_spend(message.from_user.id, item["price"], "shop_buy", "Ящик удачи")
        if after_spend is None:
            bal = await get_balance(message.from_user.id)
            return await message.answer(f"💸 Не хватает монет! У тебя: <b>{bal:,}</b>", parse_mode="HTML")
        prize = random.randint(500, 5000)
        new_bal = await update_balance(message.from_user.id, prize, "lucky_box", f"Выиграно: {prize}")
        await add_purchase(message.from_user.id, item_key, item["price"])
        await message.answer(
            f"🎲 <b>ЯЩИК УДАЧИ</b>\n\n"
            f"Ты открываешь ящик и находишь...\n"
            f"💰 <b>{prize:,}</b> монет!\n\n"
            f"💵 Баланс: <b>{new_bal:,}</b>",
            parse_mode="HTML"
        )
        return

    if item_key == "mega_box":
        after_spend = await safe_spend(message.from_user.id, item["price"], "shop_buy", "Мега-ящик")
        if after_spend is None:
            bal = await get_balance(message.from_user.id)
            return await message.answer(f"💸 Не хватает монет! У тебя: <b>{bal:,}</b>", parse_mode="HTML")
        prize = random.randint(5000, 30000)
        new_bal = await update_balance(message.from_user.id, prize, "mega_box", f"Выиграно: {prize}")
        await add_purchase(message.from_user.id, item_key, item["price"])
        await message.answer(
            f"🎁 <b>МЕГА-ЯЩИК</b>\n\n"
            f"Ты открываешь огромный ящик и находишь...\n"
            f"💰 <b>{prize:,}</b> монет!\n\n"
            f"💵 Баланс: <b>{new_bal:,}</b>",
            parse_mode="HTML"
        )
        return

    if item_key == "rep_boost":
        from db.database import add_reputation
        after_spend = await safe_spend(message.from_user.id, item["price"], "shop_buy", "Буст репутации")
        if after_spend is None:
            bal = await get_balance(message.from_user.id)
            return await message.answer(f"💸 Не хватает монет! У тебя: <b>{bal:,}</b>", parse_mode="HTML")
        new_rep = await add_reputation(message.from_user.id, 50)
        await add_purchase(message.from_user.id, item_key, item["price"])
        new_bal = await get_balance(message.from_user.id)
        await message.answer(
            f"⚡ <b>БУСТ РЕПУТАЦИИ</b>\n\n"
            f"Репутация: +50 → <b>{new_rep}</b> ✨\n"
            f"💵 Баланс: <b>{new_bal:,}</b>",
            parse_mode="HTML"
        )
        return

    if item_key == "boosti_sub":
        boosti_link = SHOP_BOOSTI_URL or LINK_BOOSTI or "Ссылка не настроена"
        extra_msg = f"\n\n📎 Ссылка для активации: {boosti_link}"

    # Стандартная покупка (VIP, Premium, Elite, custom_title, boosti_sub)
    after_spend = await safe_spend(message.from_user.id, item["price"], "shop_buy", item["name"])
    if after_spend is None:
        bal = await get_balance(message.from_user.id)
        return await message.answer(f"💸 Не хватает монет! У тебя: <b>{bal:,}</b>", parse_mode="HTML")
    await add_purchase(message.from_user.id, item_key, item["price"])

    # Для статусов - автоматическая активация
    if item_key in ("vip", "premium", "elite"):
        duration = {"vip": "30 дней", "premium": "14 дней", "elite": "7 дней"}[item_key]
        await message.answer(
            f"🛒 <b>Статус активирован!</b>\n\n"
            f"📦 {item['name']}\n"
            f"⏰ Срок действия: <b>{duration}</b>\n"
            f"💵 Баланс: <b>{after_spend:,}</b>",
            parse_mode="HTML"
        )
        return

    await message.answer(
        f"🛒 <b>Покупка совершена!</b>\n\n"
        f"📦 {item['name']}\n"
        f"💰 Стоимость: <b>{item['price']:,}</b> монет\n"
        f"💵 Баланс: <b>{after_spend:,}</b>{extra_msg}\n\n"
        f"<i>Свяжись с админом для активации товара.</i>",
        parse_mode="HTML"
    )
