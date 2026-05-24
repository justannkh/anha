import os
import aiosqlite
import asyncio

DB_PATH = os.getenv("DB_PATH", "bot.db")

ROLES = {
    "owner":  0,
    "friend": 1,
    "admin":  2,
    "moder":  3,
    "user":   4,
}

ROLE_NAMES = {v: k for k, v in ROLES.items()}

ROLE_LABELS = {
    "owner":  "\U0001f451 Овнер",
    "friend": "\U0001f31f Друг",
    "admin":  "\u2699\ufe0f Админ",
    "moder":  "\U0001f6e1 Модер",
    "user":   "\U0001f464 Юзер",
}

# ══════════════════════════════════════════════════════════════════
#  ЕДИНОЕ СОЕДИНЕНИЕ — решает проблему "database is locked"
# ══════════════════════════════════════════════════════════════════

_db: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    """Возвращает единое соединение с БД. Создаёт при первом вызове."""
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        # WAL-режим: позволяет читать параллельно с записью
        await _db.execute("PRAGMA journal_mode=WAL")
        # Таймаут на блокировку — 30 секунд вместо дефолтных 5
        await _db.execute("PRAGMA busy_timeout=30000")
    return _db


async def init_db():
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            full_name     TEXT,
            role          INTEGER DEFAULT 4,
            warns         INTEGER DEFAULT 0,
            is_banned     INTEGER DEFAULT 0,
            is_muted      INTEGER DEFAULT 0,
            ban_reason    TEXT    DEFAULT '',
            mute_reason   TEXT    DEFAULT '',
            message_count INTEGER DEFAULT 0,
            reputation    INTEGER DEFAULT 0,
            balance       INTEGER DEFAULT 0,
            daily_streak  INTEGER DEFAULT 0,
            last_daily    TEXT    DEFAULT '',
            joined_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for col, defn in [
        ("is_muted",      "INTEGER DEFAULT 0"),
        ("ban_reason",    "TEXT DEFAULT ''"),
        ("mute_reason",   "TEXT DEFAULT ''"),
        ("message_count", "INTEGER DEFAULT 0"),
        ("reputation",    "INTEGER DEFAULT 0"),
        ("balance",       "INTEGER DEFAULT 0"),
        ("daily_streak",  "INTEGER DEFAULT 0"),
        ("last_daily",    "TEXT DEFAULT ''"),
        ("last_weekly",   "TEXT DEFAULT ''"),
        ("last_work",     "TEXT DEFAULT ''"),
        ("work_count",    "INTEGER DEFAULT 0"),
    ]:
        try:
            await db.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
        except Exception:
            pass

    await db.execute("""
        CREATE TABLE IF NOT EXISTS warn_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            mod_id     INTEGER NOT NULL,
            reason     TEXT    DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS ai_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            role       TEXT,
            content    TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS user_personas (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            tone       TEXT NOT NULL,
            facts      TEXT NOT NULL DEFAULT '',
            nick       TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS marriages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id   INTEGER NOT NULL,
            user2_id   INTEGER NOT NULL,
            chat_id    INTEGER NOT NULL,
            married_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user1_id, chat_id),
            UNIQUE(user2_id, chat_id)
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS marriage_proposals (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id    INTEGER NOT NULL,
            to_id      INTEGER NOT NULL,
            chat_id    INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_id, chat_id)
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            amount     INTEGER NOT NULL,
            tx_type    TEXT NOT NULL DEFAULT '',
            detail     TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS shop_purchases (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            item_key   TEXT NOT NULL,
            price      INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS rep_cooldowns (
            user_id    INTEGER NOT NULL,
            target_id  INTEGER NOT NULL,
            used_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, target_id)
        )
    """)

    # Таблица правил чата
    await db.execute("""
        CREATE TABLE IF NOT EXISTS chat_rules (
            chat_id  INTEGER PRIMARY KEY,
            rules    TEXT NOT NULL DEFAULT ''
        )
    """)

    await db.commit()

    # Создаём фейкового юзера «Анха» для брака с овнером
    await db.execute("""
        INSERT OR IGNORE INTO users (user_id, username, full_name, role)
        VALUES (0, 'ankha_bot', 'Анха 🖤', 4)
    """)
    await db.commit()


async def ensure_owner_marriage(owner_id: int, group_ids: list[int]):
    """Гарантирует запись брака овнера с Анхой (id=0) в каждой группе."""
    db = await get_db()
    for gid in group_ids:
        # Проверяем, есть ли уже
        async with db.execute(
            "SELECT id FROM marriages WHERE user1_id = ? AND user2_id = 0 AND chat_id = ?",
            (owner_id, gid)
        ) as cur:
            if await cur.fetchone():
                continue
        # Удаляем конфликтные записи (если вдруг owner женат на ком-то ещё)
        # НЕ удаляем — пусть будет и тот и этот, unique constraint на user1+chat
        try:
            await db.execute(
                "INSERT INTO marriages (user1_id, user2_id, chat_id, married_at) "
                "VALUES (?, 0, ?, datetime('now', '-365 days'))",
                (owner_id, gid)
            )
        except Exception:
            pass  # уже есть или конфликт — ок
    await db.commit()


# ── Пользователи ──────────────────────────────────────────────────

async def get_user(user_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_user_by_username(username: str) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users WHERE lower(username) = lower(?)",
        (username.lstrip("@"),)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def upsert_user(user_id: int, username: str, full_name: str):
    db = await get_db()
    await db.execute("""
        INSERT INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username  = excluded.username,
            full_name = excluded.full_name
    """, (user_id, username, full_name))
    await db.commit()


async def increment_messages(user_id: int):
    db = await get_db()
    await db.execute(
        "UPDATE users SET message_count = message_count + 1 WHERE user_id = ?",
        (user_id,)
    )
    await db.commit()


async def get_top_messages(limit: int = 10) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users ORDER BY message_count DESC LIMIT ?", (limit,)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# ── Роли ──────────────────────────────────────────────────────────

async def get_role(user_id: int) -> str:
    user = await get_user(user_id)
    if not user:
        return "user"
    return ROLE_NAMES.get(user["role"], "user")


async def set_role(user_id: int, role: str):
    db = await get_db()
    await db.execute(
        "UPDATE users SET role = ? WHERE user_id = ?",
        (ROLES[role], user_id)
    )
    await db.commit()


# ── Варны ─────────────────────────────────────────────────────────

async def add_warn(user_id: int, mod_id: int, reason: str = "") -> int:
    db = await get_db()
    await db.execute(
        "UPDATE users SET warns = warns + 1 WHERE user_id = ?", (user_id,)
    )
    await db.execute(
        "INSERT INTO warn_log (user_id, mod_id, reason) VALUES (?, ?, ?)",
        (user_id, mod_id, reason)
    )
    await db.commit()
    async with db.execute(
        "SELECT warns FROM users WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


async def reset_warns(user_id: int):
    db = await get_db()
    await db.execute("UPDATE users SET warns = 0 WHERE user_id = ?", (user_id,))
    await db.commit()


async def get_warn_log(user_id: int, limit: int = 5) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM warn_log WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# ── Бан / Мут ─────────────────────────────────────────────────────

async def set_ban(user_id: int, banned: bool, reason: str = ""):
    db = await get_db()
    if banned:
        await db.execute(
            "UPDATE users SET is_banned = 1, ban_reason = ? WHERE user_id = ?",
            (reason, user_id)
        )
    else:
        await db.execute(
            "UPDATE users SET is_banned = 0, ban_reason = '' WHERE user_id = ?",
            (user_id,)
        )
    await db.commit()


async def set_mute(user_id: int, muted: bool, reason: str = ""):
    db = await get_db()
    if muted:
        await db.execute(
            "UPDATE users SET is_muted = 1, mute_reason = ? WHERE user_id = ?",
            (reason, user_id)
        )
    else:
        await db.execute(
            "UPDATE users SET is_muted = 0, mute_reason = '' WHERE user_id = ?",
            (user_id,)
        )
    await db.commit()


# ── Репутация ─────────────────────────────────────────────────────

async def add_reputation(user_id: int, amount: int) -> int:
    db = await get_db()
    await db.execute(
        "UPDATE users SET reputation = reputation + ? WHERE user_id = ?",
        (amount, user_id)
    )
    await db.commit()
    async with db.execute(
        "SELECT reputation FROM users WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_top_reputation(limit: int = 10) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users WHERE reputation > 0 ORDER BY reputation DESC LIMIT ?",
        (limit,)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def check_rep_cooldown(user_id: int, target_id: int, seconds: int = 3600) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT used_at FROM rep_cooldowns WHERE user_id = ? AND target_id = ? "
        "AND used_at > datetime('now', ?)",
        (user_id, target_id, f"-{seconds} seconds")
    ) as cur:
        row = await cur.fetchone()
        return row is not None


async def set_rep_cooldown(user_id: int, target_id: int):
    db = await get_db()
    await db.execute("""
        INSERT INTO rep_cooldowns (user_id, target_id, used_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, target_id) DO UPDATE SET used_at = CURRENT_TIMESTAMP
    """, (user_id, target_id))
    await db.commit()


async def count_rep_received_today(target_id: int) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM rep_cooldowns WHERE target_id = ? "
        "AND used_at > datetime('now', '-1 day')",
        (target_id,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


# ── Экономика ─────────────────────────────────────────────────────

async def get_balance(user_id: int) -> int:
    user = await get_user(user_id)
    return user["balance"] if user else 0


async def update_balance(user_id: int, amount: int, tx_type: str = "", detail: str = "") -> int:
    db = await get_db()
    await db.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (amount, user_id)
    )
    if tx_type:
        await db.execute(
            "INSERT INTO transactions (user_id, amount, tx_type, detail) VALUES (?, ?, ?, ?)",
            (user_id, amount, tx_type, detail)
        )
    await db.commit()
    async with db.execute(
        "SELECT balance FROM users WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


async def safe_spend(user_id: int, amount: int, tx_type: str = "", detail: str = "") -> int | None:
    """
    Атомарное списание: списывает amount ТОЛЬКО если баланс >= amount.
    Возвращает новый баланс или None если денег не хватает.
    """
    db = await get_db()
    cursor = await db.execute(
        "UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
        (amount, user_id, amount)
    )
    if cursor.rowcount == 0:
        return None
    if tx_type:
        await db.execute(
            "INSERT INTO transactions (user_id, amount, tx_type, detail) VALUES (?, ?, ?, ?)",
            (user_id, -amount, tx_type, detail)
        )
    await db.commit()
    async with db.execute(
        "SELECT balance FROM users WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else 0


async def get_daily_info(user_id: int) -> tuple[str, int]:
    user = await get_user(user_id)
    if not user:
        return "", 0
    return user.get("last_daily", "") or "", user.get("daily_streak", 0) or 0


async def set_daily_info(user_id: int, date_str: str, streak: int):
    db = await get_db()
    await db.execute(
        "UPDATE users SET last_daily = ?, daily_streak = ? WHERE user_id = ?",
        (date_str, streak, user_id)
    )
    await db.commit()


async def get_weekly_info(user_id: int) -> str:
    user = await get_user(user_id)
    if not user:
        return ""
    return user.get("last_weekly", "") or ""


async def set_weekly_info(user_id: int, week_str: str):
    db = await get_db()
    await db.execute(
        "UPDATE users SET last_weekly = ? WHERE user_id = ?",
        (week_str, user_id)
    )
    await db.commit()


async def get_work_info(user_id: int) -> tuple[str, int]:
    """Возвращает (last_work_date, work_count_today)."""
    user = await get_user(user_id)
    if not user:
        return "", 0
    return user.get("last_work", "") or "", user.get("work_count", 0) or 0


async def set_work_info(user_id: int, date_str: str, count: int):
    db = await get_db()
    await db.execute(
        "UPDATE users SET last_work = ?, work_count = ? WHERE user_id = ?",
        (date_str, count, user_id)
    )
    await db.commit()


async def get_top_balance(limit: int = 10) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM users WHERE balance > 0 ORDER BY balance DESC LIMIT ?",
        (limit,)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# ── Браки ─────────────────────────────────────────────────────────

async def get_marriage(user_id: int, chat_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM marriages WHERE (user1_id = ? OR user2_id = ?) AND chat_id = ?",
        (user_id, user_id, chat_id)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_marriage(user1_id: int, user2_id: int, chat_id: int) -> bool:
    try:
        db = await get_db()
        await db.execute(
            "INSERT INTO marriages (user1_id, user2_id, chat_id) VALUES (?, ?, ?)",
            (user1_id, user2_id, chat_id)
        )
        await db.commit()
        return True
    except Exception:
        return False


async def delete_marriage(user_id: int, chat_id: int) -> bool:
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM marriages WHERE (user1_id = ? OR user2_id = ?) AND chat_id = ?",
        (user_id, user_id, chat_id)
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_all_marriages(chat_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM marriages WHERE chat_id = ? ORDER BY married_at ASC",
        (chat_id,)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def get_top_marriages(chat_id: int, limit: int = 10) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM marriages WHERE chat_id = ? ORDER BY married_at ASC LIMIT ?",
        (chat_id, limit)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# ── Предложения брака ─────────────────────────────────────────────

async def create_proposal(from_id: int, to_id: int, chat_id: int) -> bool:
    try:
        db = await get_db()
        await db.execute(
            "DELETE FROM marriage_proposals WHERE from_id = ? AND chat_id = ?",
            (from_id, chat_id)
        )
        await db.execute(
            "INSERT INTO marriage_proposals (from_id, to_id, chat_id) VALUES (?, ?, ?)",
            (from_id, to_id, chat_id)
        )
        await db.commit()
        return True
    except Exception:
        return False


async def get_proposal_for(to_id: int, chat_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM marriage_proposals WHERE to_id = ? AND chat_id = ?",
        (to_id, chat_id)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_proposal(to_id: int, chat_id: int):
    db = await get_db()
    await db.execute(
        "DELETE FROM marriage_proposals WHERE to_id = ? AND chat_id = ?",
        (to_id, chat_id)
    )
    await db.commit()


# ── Покупки ───────────────────────────────────────────────────────

async def add_purchase(user_id: int, item_key: str, price: int):
    db = await get_db()
    await db.execute(
        "INSERT INTO shop_purchases (user_id, item_key, price) VALUES (?, ?, ?)",
        (user_id, item_key, price)
    )
    await db.commit()


async def get_purchases(user_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM shop_purchases WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# ── Персоны ───────────────────────────────────────────────────────

async def set_persona(user_id: int, username: str, tone: str, facts: str, nick: str):
    db = await get_db()
    await db.execute("""
        INSERT INTO user_personas (user_id, username, tone, facts, nick, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            username   = excluded.username,
            tone       = excluded.tone,
            facts      = excluded.facts,
            nick       = excluded.nick,
            updated_at = CURRENT_TIMESTAMP
    """, (user_id, username, tone, facts, nick))
    await db.commit()


async def get_persona(user_id: int) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM user_personas WHERE user_id = ?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_persona(user_id: int):
    db = await get_db()
    await db.execute("DELETE FROM user_personas WHERE user_id = ?", (user_id,))
    await db.commit()


async def list_personas() -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM user_personas ORDER BY updated_at DESC"
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# ── Глобальные настройки ──────────────────────────────────────────

async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    async with db.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    db = await get_db()
    await db.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, value))
    await db.commit()


# ── Очистка ───────────────────────────────────────────────────────

async def purge_old_ai_history(days: int = 3):
    db = await get_db()
    await db.execute(
        "DELETE FROM ai_history WHERE created_at < datetime('now', ?)",
        (f"-{days} days",)
    )
    await db.commit()


async def purge_old_proposals(hours: int = 24):
    db = await get_db()
    await db.execute(
        "DELETE FROM marriage_proposals WHERE created_at < datetime('now', ?)",
        (f"-{hours} hours",)
    )
    await db.commit()


async def purge_old_cooldowns(seconds: int = 3600):
    db = await get_db()
    await db.execute(
        "DELETE FROM rep_cooldowns WHERE used_at < datetime('now', ?)",
        (f"-{seconds} seconds",)
    )
    await db.commit()


# ── Правила чата ──────────────────────────────────────────────────

async def get_rules(chat_id: int) -> str:
    db = await get_db()
    async with db.execute(
        "SELECT rules FROM chat_rules WHERE chat_id = ?", (chat_id,)
    ) as cur:
        row = await cur.fetchone()
        return row[0] if row else ""


async def set_rules(chat_id: int, rules: str):
    db = await get_db()
    await db.execute("""
        INSERT INTO chat_rules (chat_id, rules) VALUES (?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET rules = excluded.rules
    """, (chat_id, rules))
    await db.commit()


# ── Проверка покупок (для ограничения повторных) ──────────────────

async def has_purchased(user_id: int, item_key: str) -> bool:
    """Проверяет, покупал ли юзер этот товар."""
    db = await get_db()
    async with db.execute(
        "SELECT id FROM shop_purchases WHERE user_id = ? AND item_key = ?",
        (user_id, item_key)
    ) as cur:
        return await cur.fetchone() is not None


async def has_active_vip(user_id: int) -> bool:
    """Проверяет, есть ли активный VIP (куплен менее 30 дней назад)."""
    db = await get_db()
    async with db.execute(
        "SELECT id FROM shop_purchases WHERE user_id = ? AND item_key = 'vip' "
        "AND created_at > datetime('now', '-30 days')",
        (user_id,)
    ) as cur:
        return await cur.fetchone() is not None


async def has_active_premium(user_id: int) -> bool:
    """Проверяет, есть ли активный Premium (куплен менее 14 дней назад)."""
    db = await get_db()
    async with db.execute(
        "SELECT id FROM shop_purchases WHERE user_id = ? AND item_key = 'premium' "
        "AND created_at > datetime('now', '-14 days')",
        (user_id,)
    ) as cur:
        return await cur.fetchone() is not None


async def has_active_elite(user_id: int) -> bool:
    """Проверяет, есть ли активный Elite (куплен менее 7 дней назад)."""
    db = await get_db()
    async with db.execute(
        "SELECT id FROM shop_purchases WHERE user_id = ? AND item_key = 'elite' "
        "AND created_at > datetime('now', '-7 days')",
        (user_id,)
    ) as cur:
        return await cur.fetchone() is not None


async def get_user_status(user_id: int) -> tuple[str, float]:
    """Возвращает (название_статуса, множитель) для юзера."""
    if await has_active_vip(user_id):
        return "💎 VIP", 2.0
    if await has_active_premium(user_id):
        return "⭐ Premium", 1.5
    if await has_active_elite(user_id):
        return "🔥 Elite", 1.25
    return "", 1.0


async def clear_ai_history():
    """Полностью очищает историю ИИ."""
    db = await get_db()
    await db.execute("DELETE FROM ai_history")
    await db.commit()

