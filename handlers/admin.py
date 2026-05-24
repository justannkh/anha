import re
from datetime import datetime, timedelta

from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message, ChatPermissions

from db.database import (
    get_user, get_user_by_username, set_role, set_ban, set_mute,
    add_warn, reset_warns, get_warn_log,
    ROLES, ROLE_LABELS, ROLE_NAMES,
    get_persona, set_persona, delete_persona, list_personas,
    clear_ai_history,
)
from utils.roles import owner_only, admin_only, moder_only

router = Router()
P = "."

MUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False, can_send_audios=False, can_send_documents=False,
    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False,
    can_send_other_messages=False, can_add_web_page_previews=False,
)
FULL_PERMISSIONS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True,
    can_send_other_messages=True, can_add_web_page_previews=True,
)


def _group_only(message: Message) -> bool:
    return message.chat.type in ("group", "supergroup")


# ── Парсер времени: "30м", "2ч", "1д", "30m", "2h", "1d" ────────

_TIME_RE = re.compile(r'^(\d+)\s*([мmhчdд])', re.IGNORECASE)

_TIME_MULTIPLIERS = {
    'м': 60, 'm': 60,           # минуты
    'ч': 3600, 'h': 3600,       # часы
    'д': 86400, 'd': 86400,     # дни
}

def _parse_duration(text: str) -> tuple[int | None, str]:
    """
    Парсит строку вида '30м причина' или '2ч флуд'.
    Возвращает (секунды, оставшаяся_причина) или (None, весь_текст).
    """
    m = _TIME_RE.match(text.strip())
    if not m:
        return None, text
    num = int(m.group(1))
    unit = m.group(2).lower()
    seconds = num * _TIME_MULTIPLIERS.get(unit, 60)
    # Telegram ограничение: мут минимум 30 сек, максимум 366 дней
    seconds = max(30, min(seconds, 366 * 86400))
    rest = text[m.end():].strip()
    return seconds, rest


def _format_duration(seconds: int) -> str:
    if seconds >= 86400:
        d = seconds // 86400
        return f"{d} дн."
    elif seconds >= 3600:
        h = seconds // 3600
        return f"{h} ч."
    else:
        m = max(1, seconds // 60)
        return f"{m} мин."


async def resolve_target(message: Message) -> tuple[int | None, str, str]:
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        if target.is_bot:
            return None, "🤖 Нельзя применять команды к боту.", ""
        parts = (message.text or "").split(None, 1)
        reason = parts[1].strip() if len(parts) > 1 else ""
        return target.id, "", reason

    parts = (message.text or "").split(None, 2)
    if len(parts) >= 2:
        arg = parts[1].lstrip("@")
        reason = parts[2].strip() if len(parts) >= 3 else ""
        if arg.isdigit():
            return int(arg), "", reason
        u = await get_user_by_username(arg)
        if u:
            return u["user_id"], "", reason

    return None, "💡 Ответь на сообщение юзера или передай его ID / @username.", ""


# ── .варн ─────────────────────────────────────────────────────────

@router.message(Command("варн", "warn", prefix=P))
@moder_only
async def cmd_warn(message: Message, bot: Bot):
    if not _group_only(message):
        return await message.answer("📍 Только в группе.")

    target_id, err, reason = await resolve_target(message)
    if err:
        return await message.answer(err)
    target = await get_user(target_id)
    if not target:
        return await message.answer("❓ Юзер не найден в базе.")

    warns = await add_warn(target_id, message.from_user.id, reason)
    reason_line = f"\n📝 <i>{reason}</i>" if reason else ""

    await message.answer(
        f"╔══════════════════════╗\n"
        f"  ⚡️ <b>ПРЕДУПРЕЖДЕНИЕ</b>\n"
        f"╚══════════════════════╝\n\n"
        f"👤 <b>{target['full_name']}</b>{reason_line}\n"
        f"📊 Варнов: <b>{warns}</b>/3\n\n"
        f"{'🔴' * warns}{'⚪️' * (3 - warns)}",
        parse_mode="HTML"
    )

    if warns >= 3:
        try:
            await bot.restrict_chat_member(message.chat.id, target_id, MUTED_PERMISSIONS)
        except Exception as e:
            await message.answer(f"⚠️ Telegram-мут не удался: {e}")
        await set_mute(target_id, True, "Лимит предупреждений")
        await reset_warns(target_id)
        await message.answer(
            f"╔══════════════════════╗\n"
            f"  🔇 <b>АВТОМАТИЧЕСКИЙ МУТ</b>\n"
            f"╚══════════════════════╝\n\n"
            f"👤 <b>{target['full_name']}</b>\n"
            f"📝 <i>Накоплено 3 предупреждения</i>",
            parse_mode="HTML"
        )


# ── .варнлог ──────────────────────────────────────────────────────

@router.message(Command("варнлог", "warnlog", prefix=P))
@moder_only
async def cmd_warnlog(message: Message):
    target_id, err, _ = await resolve_target(message)
    if err:
        return await message.answer(err)
    target = await get_user(target_id)
    if not target:
        return await message.answer("❓ Юзер не найден.")

    log = await get_warn_log(target_id, 10)
    if not log:
        return await message.answer(
            f"✅ У <b>{target['full_name']}</b> чистая история — варнов нет.",
            parse_mode="HTML"
        )

    lines = [
        f"📋 <b>История предупреждений</b>\n"
        f"👤 {target['full_name']}\n"
    ]
    for i, w in enumerate(log, 1):
        r = w.get("reason") or "без причины"
        dt = w.get("created_at", "")[:10]
        lines.append(f"  {i}. 📅 {dt} — {r}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── .снятьварн ────────────────────────────────────────────────────

@router.message(Command("снятьварн", "unwarn", prefix=P))
@moder_only
async def cmd_unwarn(message: Message):
    target_id, err, _ = await resolve_target(message)
    if err:
        return await message.answer(err)
    target = await get_user(target_id)
    if not target:
        return await message.answer("❓ Юзер не найден.")
    await reset_warns(target_id)
    await message.answer(
        f"🧹 Все предупреждения <b>{target['full_name']}</b> сброшены!\n"
        f"Теперь чист, как слеза.",
        parse_mode="HTML"
    )


# ── .мут ──────────────────────────────────────────────────────────

@router.message(Command("мут", "mute", prefix=P))
@moder_only
async def cmd_mute(message: Message, bot: Bot):
    if not _group_only(message):
        return await message.answer("📍 Только в группе.")

    # Формат: .мут [время] @user/реплай [причина]
    # или: .мут @user/реплай [время] [причина]
    target_id, err, reason = await resolve_target(message)
    if err:
        return await message.answer(err)
    target = await get_user(target_id)
    if not target:
        return await message.answer("❓ Юзер не найден.")

    # Пробуем найти время в reason
    duration_sec, clean_reason = _parse_duration(reason)

    try:
        if duration_sec:
            until = datetime.utcnow() + timedelta(seconds=duration_sec)
            await bot.restrict_chat_member(
                message.chat.id, target_id, MUTED_PERMISSIONS,
                until_date=until
            )
            time_str = _format_duration(duration_sec)
        else:
            await bot.restrict_chat_member(message.chat.id, target_id, MUTED_PERMISSIONS)
            time_str = "навсегда"

        await set_mute(target_id, True, clean_reason)
        reason_line = f"\n📝 <i>{clean_reason}</i>" if clean_reason else ""
        await message.answer(
            f"╔══════════════════════╗\n"
            f"  🔇 <b>МУТ</b>\n"
            f"╚══════════════════════╝\n\n"
            f"👤 <b>{target['full_name']}</b>{reason_line}\n"
            f"⏰ Срок: <b>{time_str}</b>\n"
            f"🤫 Молчание — золото.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"⚠️ Не удалось: {e}")


# ── .размут ────────────────────────────────────────────────────────

@router.message(Command("размут", "unmute", prefix=P))
@moder_only
async def cmd_unmute(message: Message, bot: Bot):
    if not _group_only(message):
        return await message.answer("📍 Только в группе.")

    target_id, err, _ = await resolve_target(message)
    if err:
        return await message.answer(err)
    target = await get_user(target_id)
    if not target:
        return await message.answer("❓ Юзер не найден.")

    try:
        await bot.restrict_chat_member(message.chat.id, target_id, FULL_PERMISSIONS)
        await set_mute(target_id, False)
        await message.answer(
            f"🔊 <b>{target['full_name']}</b> снова может говорить!\n"
            f"Используй эту возможность с умом.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"⚠️ Не удалось: {e}")


# ── .бан ──────────────────────────────────────────────────────────

@router.message(Command("бан", "ban", prefix=P))
@admin_only
async def cmd_ban(message: Message, bot: Bot):
    if not _group_only(message):
        return await message.answer("📍 Только в группе.")

    target_id, err, reason = await resolve_target(message)
    if err:
        return await message.answer(err)
    target = await get_user(target_id)
    if not target:
        return await message.answer("❓ Юзер не найден.")

    try:
        await bot.ban_chat_member(message.chat.id, target_id)
        await set_ban(target_id, True, reason)
        reason_line = f"\n📝 <i>{reason}</i>" if reason else ""
        await message.answer(
            f"╔══════════════════════╗\n"
            f"  🔨 <b>БАН</b>\n"
            f"╚══════════════════════╝\n\n"
            f"👤 <b>{target['full_name']}</b>{reason_line}\n\n"
            f"🚪 Дверь закрыта.\n"
            f"🔓 Разбан: <code>{P}разбан {target_id}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"⚠️ Не удалось: {e}")


# ── .разбан ────────────────────────────────────────────────────────

@router.message(Command("разбан", "unban", prefix=P))
@admin_only
async def cmd_unban(message: Message, bot: Bot):
    target_id, err, _ = await resolve_target(message)
    if err:
        return await message.answer(err)
    target = await get_user(target_id)
    if not target:
        return await message.answer("❓ Юзер не найден.")

    try:
        await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
        await set_ban(target_id, False)
        await message.answer(
            f"🔓 <b>{target['full_name']}</b> разбанен!\n"
            f"Добро пожаловать обратно... может быть.",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"⚠️ Не удалось: {e}")


# ── .роль ─────────────────────────────────────────────────────────

@router.message(Command("роль", "setrole", prefix=P))
@admin_only
async def cmd_setrole(message: Message, user_db: dict):
    parts = (message.text or "").split()
    if len(parts) < 3:
        return await message.answer(
            f"💡 Формат: {P}роль ID роль\n"
            "Роли: owner, friend, admin, moder, user"
        )

    arg      = parts[1].lstrip("@")
    role_str = parts[2].lower()

    if role_str not in ROLES:
        return await message.answer("❌ Неверная роль.")

    caller_level = user_db["role"]
    target_level = ROLES[role_str]
    if target_level < caller_level:
        return await message.answer("⛔ Нельзя выдать роль выше своей.")

    target_db = None
    if arg.isdigit():
        target_db = await get_user(int(arg))
    else:
        target_db = await get_user_by_username(arg)
    if not target_db:
        return await message.answer("❓ Юзер не найден.")

    await set_role(target_db["user_id"], role_str)
    await message.answer(
        f"✅ Роль <b>{ROLE_LABELS[role_str]}</b> выдана <b>{target_db['full_name']}</b>.",
        parse_mode="HTML"
    )


# ── Персоны ────────────────────────────────────────────────────────

@router.message(Command("персона", "persona", prefix=P))
@owner_only
async def cmd_persona(message: Message):
    parts = (message.text or "").split(None, 2)

    if len(parts) == 1:
        all_p = await list_personas()
        if not all_p:
            return await message.answer("🎭 Персон пока нет.")
        lines = ["🎭 <b>Персоны:</b>\n"]
        for p in all_p:
            uname = f"@{p['username']}" if p.get("username") else f"id{p['user_id']}"
            nick  = p.get("nick") or "—"
            lines.append(f"  • {uname}  (ник: {nick})")
        return await message.answer("\n".join(lines), parse_mode="HTML")

    target_db = None
    if message.reply_to_message and message.reply_to_message.from_user:
        ru = message.reply_to_message.from_user
        if not ru.is_bot:
            target_db = await get_user(ru.id)
    if not target_db:
        raw = parts[1].lstrip("@")
        target_db = await get_user(int(raw)) if raw.isdigit() else await get_user_by_username(raw)
    if not target_db:
        return await message.answer("❓ Юзер не найден. Он должен хоть раз написать в чате.")

    if len(parts) == 2:
        p = await get_persona(target_db["user_id"])
        if not p:
            return await message.answer(f"У {target_db['full_name']} нет персоны.")
        p_facts = p['facts'] or '—'
        p_nick  = p['nick']  or '—'
        await message.answer(
            f"🎭 <b>Персона</b> — {target_db['full_name']}\n\n"
            f"<b>Тон:</b> {p['tone']}\n"
            f"<b>Факты:</b> {p_facts}\n"
            f"<b>Ник:</b> {p_nick}",
            parse_mode="HTML"
        )
        return

    raw_data = parts[2]
    chunks   = [c.strip() for c in raw_data.split(",")]
    tone  = chunks[0] if len(chunks) > 0 else ""
    facts = chunks[1] if len(chunks) > 1 else ""
    nick  = chunks[2] if len(chunks) > 2 else ""

    if not tone:
        return await message.answer(
            f"💡 Формат: {P}персона @user тон, факты, ник\n"
            "Факты и ник необязательны."
        )

    await set_persona(
        user_id=target_db["user_id"],
        username=target_db.get("username") or "",
        tone=tone, facts=facts, nick=nick,
    )
    uname      = f"@{target_db['username']}" if target_db.get("username") else target_db["full_name"]
    facts_disp = facts or '—'
    nick_disp  = nick  or '—'
    await message.answer(
        f"✅ Персона задана для {uname}.\n\n"
        f"<b>Тон:</b> {tone}\n"
        f"<b>Факты:</b> {facts_disp}\n"
        f"<b>Ник:</b> {nick_disp}",
        parse_mode="HTML"
    )


@router.message(Command("делперс", "delpersona", prefix=P))
@owner_only
async def cmd_del_persona(message: Message):
    target_id, err, _ = await resolve_target(message)
    if err:
        return await message.answer(err)
    target = await get_user(target_id)
    if not target:
        return await message.answer("❓ Юзер не найден.")
    await delete_persona(target_id)
    await message.answer(
        f"✅ Персона удалена у <b>{target['full_name']}</b>.", parse_mode="HTML"
    )


# ── .сброс ────────────────────────────────────────────────────────

@router.message(Command("сброс", "reset", prefix=P))
@owner_only
async def cmd_reset_ai(message: Message):
    """Полностью сбрасывает историю ИИ и память."""
    # Сбрасываем in-memory кэш
    from handlers.ai_chat import _histories
    _histories.clear()
    
    # Очищаем БД
    await clear_ai_history()
    
    await message.answer(
        "🧹 <b>ИИ сброшен!</b>\n\n"
        "✅ История диалогов очищена\n"
        "✅ База данных ИИ очищена\n"
        "✅ Персоны сохранены\n\n"
        "<i>Анха забыла всё, кроме своего характера и отношения к юзерам.</i>",
        parse_mode="HTML"
    )
