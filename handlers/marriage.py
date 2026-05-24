from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from db.database import (
    get_user, get_user_by_username,
    get_marriage, create_marriage, delete_marriage,
    get_all_marriages, get_top_marriages,
    create_proposal, get_proposal_for, delete_proposal,
)
from utils.roles import owner_only

router = Router()
P = "."


def _marriage_duration(married_at_str: str) -> str:
    """Красиво форматирует длительность брака."""
    try:
        dt = datetime.fromisoformat(married_at_str)
    except (ValueError, TypeError):
        try:
            dt = datetime.strptime(married_at_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return "?"
    delta = datetime.utcnow() - dt
    days = delta.days
    if days == 0:
        hours = delta.seconds // 3600
        return f"{hours} ч." if hours > 0 else "только что"
    elif days < 30:
        return f"{days} дн."
    elif days < 365:
        months = days // 30
        return f"{months} мес."
    else:
        years = days // 365
        months = (days % 365) // 30
        return f"{years} г. {months} мес." if months else f"{years} г."


# ── .брак ─────────────────────────────────────────────────────────

@router.message(Command("брак", "marry", "свадьба", prefix=P))
async def cmd_marry(message: Message, user_db: dict):
    chat_id = message.chat.id
    if message.chat.type == "private":
        return await message.answer("📍 Браки работают только в группе.")

    user_id = message.from_user.id

    # Уже в браке?
    existing = await get_marriage(user_id, chat_id)
    if existing:
        partner_id = existing["user2_id"] if existing["user1_id"] == user_id else existing["user1_id"]
        partner = await get_user(partner_id)
        partner_name = partner["full_name"] if partner else f"id{partner_id}"
        dur = _marriage_duration(existing["married_at"])
        return await message.answer(
            f"💍 Ты уже в браке с <b>{partner_name}</b>!\n"
            f"⏰ Вместе: {dur}\n\n"
            f"Развод: <code>{P}развод</code>",
            parse_mode="HTML"
        )

    # Ищем цель
    target_user = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
    else:
        parts = (message.text or "").split(None, 1)
        if len(parts) >= 2:
            arg = parts[1].lstrip("@")
            if arg.isdigit():
                t = await get_user(int(arg))
            else:
                t = await get_user_by_username(arg)
            if t:
                # Создаём фейковый объект-подобие
                target_user = type("FakeUser", (), {
                    "id": t["user_id"],
                    "full_name": t["full_name"],
                    "is_bot": False,
                })()

    if not target_user:
        return await message.answer(
            f"💍 <b>Предложение руки и сердца</b>\n\n"
            f"Формат: <code>{P}брак @юзер</code>\n"
            f"Или ответом на сообщение.\n\n"
            f"Другие команды:\n"
            f"  <code>{P}мойбрак</code> — инфо о браке\n"
            f"  <code>{P}развод</code> — расторжение\n"
            f"  <code>{P}браки</code> — список браков\n"
            f"  <code>{P}топбраков</code> — топ по длительности",
            parse_mode="HTML"
        )

    if hasattr(target_user, "is_bot") and target_user.is_bot:
        return await message.answer("🤖 Нельзя жениться на боте!")
    if target_user.id == user_id:
        return await message.answer("😅 Нельзя жениться на самом себе!")

    # Цель уже в браке?
    target_existing = await get_marriage(target_user.id, chat_id)
    if target_existing:
        return await message.answer(
            f"💔 <b>{target_user.full_name}</b> уже в браке.",
            parse_mode="HTML"
        )

    # Создаём предложение
    await create_proposal(user_id, target_user.id, chat_id)
    await message.answer(
        f"╔══════════════════════╗\n"
        f"  💍 <b>ПРЕДЛОЖЕНИЕ</b>\n"
        f"╚══════════════════════╝\n\n"
        f"💕 <b>{message.from_user.full_name}</b> предлагает\n"
        f"   <b>{target_user.full_name}</b> руку и сердце!\n\n"
        f"✅ Принять: <code>{P}бракда</code>\n"
        f"❌ Отклонить: <code>{P}бракнет</code>\n\n"
        f"<i>Предложение действует 24 часа.</i>",
        parse_mode="HTML"
    )


# ── .бракда ───────────────────────────────────────────────────────

@router.message(Command("бракда", "marryyes", prefix=P))
async def cmd_marry_accept(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    proposal = await get_proposal_for(user_id, chat_id)
    if not proposal:
        return await message.answer("💡 Тебе никто не предлагал брак.")

    # Проверяем, что оба не в браке
    if await get_marriage(user_id, chat_id):
        await delete_proposal(user_id, chat_id)
        return await message.answer("💔 Ты уже в браке!")

    if await get_marriage(proposal["from_id"], chat_id):
        await delete_proposal(user_id, chat_id)
        return await message.answer("💔 Тот, кто делал предложение, уже в браке.")

    success = await create_marriage(proposal["from_id"], user_id, chat_id)
    await delete_proposal(user_id, chat_id)

    if not success:
        return await message.answer("❌ Не удалось создать брак. Попробуйте ещё раз.")

    from_user = await get_user(proposal["from_id"])
    from_name = from_user["full_name"] if from_user else f"id{proposal['from_id']}"

    await message.answer(
        f"╔══════════════════════╗\n"
        f"  💒 <b>СВАДЬБА!</b> 💒\n"
        f"╚══════════════════════╝\n\n"
        f"💕 <b>{from_name}</b> & <b>{message.from_user.full_name}</b>\n"
        f"теперь официально вместе! 💍\n\n"
        f"🥂 Совет да любовь!\n\n"
        f"<i>Инфо: {P}мойбрак</i>",
        parse_mode="HTML"
    )


# ── .бракнет ──────────────────────────────────────────────────────

@router.message(Command("бракнет", "marryno", prefix=P))
async def cmd_marry_reject(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    proposal = await get_proposal_for(user_id, chat_id)
    if not proposal:
        return await message.answer("💡 Тебе никто не предлагал брак.")

    from_user = await get_user(proposal["from_id"])
    from_name = from_user["full_name"] if from_user else f"id{proposal['from_id']}"

    await delete_proposal(user_id, chat_id)
    await message.answer(
        f"💔 <b>{message.from_user.full_name}</b> отклоняет предложение от <b>{from_name}</b>.\n"
        f"<i>Не судьба...</i>",
        parse_mode="HTML"
    )


# ── .развод ───────────────────────────────────────────────────────

@router.message(Command("развод", "divorce", prefix=P))
async def cmd_divorce(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    marriage = await get_marriage(user_id, chat_id)
    if not marriage:
        return await message.answer("💡 Ты не в браке.")

    partner_id = marriage["user2_id"] if marriage["user1_id"] == user_id else marriage["user1_id"]

    # Нельзя развестись с Анхой
    if partner_id == 0:
        return await message.answer("🖤 Анха не отпустит тебя. Даже не пытайся.")

    partner = await get_user(partner_id)
    partner_name = partner["full_name"] if partner else f"id{partner_id}"
    dur = _marriage_duration(marriage["married_at"])

    await delete_marriage(user_id, chat_id)
    await message.answer(
        f"💔 <b>Развод</b>\n\n"
        f"👤 <b>{message.from_user.full_name}</b> & <b>{partner_name}</b>\n"
        f"⏰ Были вместе: {dur}\n\n"
        f"<i>Что ж, бывает...</i>",
        parse_mode="HTML"
    )


# ── .мойбрак ──────────────────────────────────────────────────────

@router.message(Command("мойбрак", "mymarriage", prefix=P))
async def cmd_mymarriage(message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    marriage = await get_marriage(user_id, chat_id)
    if not marriage:
        return await message.answer("💍 Ты пока не в браке. Свободен как ветер!")

    partner_id = marriage["user2_id"] if marriage["user1_id"] == user_id else marriage["user1_id"]
    partner = await get_user(partner_id)
    partner_name = partner["full_name"] if partner else f"id{partner_id}"
    dur = _marriage_duration(marriage["married_at"])

    await message.answer(
        f"💍 <b>Твой брак</b>\n\n"
        f"👫 <b>{message.from_user.full_name}</b> & <b>{partner_name}</b>\n"
        f"📅 Дата свадьбы: {marriage['married_at'][:10]}\n"
        f"⏰ Вместе: <b>{dur}</b>\n\n"
        f"💕 <i>Берегите друг друга!</i>",
        parse_mode="HTML"
    )


# ── .браки ────────────────────────────────────────────────────────

@router.message(Command("браки", "marriages", prefix=P))
async def cmd_marriages(message: Message):
    chat_id = message.chat.id
    all_m = await get_all_marriages(chat_id)
    if not all_m:
        return await message.answer("💍 В этом чате пока нет ни одного брака.")

    lines = [
        f"💍 <b>Браки чата</b>\n"
        f"Всего пар: <b>{len(all_m)}</b>\n"
    ]
    for i, m in enumerate(all_m, 1):
        u1 = await get_user(m["user1_id"])
        u2 = await get_user(m["user2_id"])
        n1 = u1["full_name"] if u1 else f"id{m['user1_id']}"
        n2 = u2["full_name"] if u2 else f"id{m['user2_id']}"
        dur = _marriage_duration(m["married_at"])
        lines.append(f"  {i}. 💕 {n1} & {n2} — {dur}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── .топбраков ────────────────────────────────────────────────────

@router.message(Command("топбраков", "topmarriages", prefix=P))
async def cmd_top_marriages(message: Message):
    chat_id = message.chat.id
    top = await get_top_marriages(chat_id, 10)
    if not top:
        return await message.answer("💍 Пока нет браков — будь первым!")

    lines = [
        "💍 <b>Топ браков — самые долгие</b>\n"
    ]
    medals = ["🥇", "🥈", "🥉"]
    for i, m in enumerate(top, 1):
        u1 = await get_user(m["user1_id"])
        u2 = await get_user(m["user2_id"])
        n1 = u1["full_name"] if u1 else f"id{m['user1_id']}"
        n2 = u2["full_name"] if u2 else f"id{m['user2_id']}"
        dur = _marriage_duration(m["married_at"])
        icon = medals[i - 1] if i <= 3 else f"<code>{i}.</code>"
        lines.append(f"  {icon} {n1} & {n2} — {dur}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ── .поженить ─────────────────────────────────────────────────────

@router.message(Command("поженить", prefix=P))
@owner_only
async def cmd_force_marry(message: Message):
    chat_id = message.chat.id
    parts = (message.text or "").split()
    if len(parts) < 3:
        return await message.answer(f"💡 Формат: <code>{P}поженить @user1 @user2</code>", parse_mode="HTML")

    # Ищем обоих
    arg1 = parts[1].lstrip("@")
    arg2 = parts[2].lstrip("@")

    u1 = await get_user(int(arg1)) if arg1.isdigit() else await get_user_by_username(arg1)
    u2 = await get_user(int(arg2)) if arg2.isdigit() else await get_user_by_username(arg2)

    if not u1 or not u2:
        return await message.answer("❓ Один из юзеров не найден.")
    if u1["user_id"] == u2["user_id"]:
        return await message.answer("😅 Нельзя поженить одного с самим собой.")

    if await get_marriage(u1["user_id"], chat_id):
        return await message.answer(f"💔 <b>{u1['full_name']}</b> уже в браке.", parse_mode="HTML")
    if await get_marriage(u2["user_id"], chat_id):
        return await message.answer(f"💔 <b>{u2['full_name']}</b> уже в браке.", parse_mode="HTML")

    success = await create_marriage(u1["user_id"], u2["user_id"], chat_id)
    if not success:
        return await message.answer("❌ Не удалось создать брак.")

    await message.answer(
        f"💒 Модератор объявляет:\n\n"
        f"💕 <b>{u1['full_name']}</b> & <b>{u2['full_name']}</b>\n"
        f"теперь муж и жена! 💍",
        parse_mode="HTML"
    )


# ── .развести ─────────────────────────────────────────────────────

@router.message(Command("развести", prefix=P))
@owner_only
async def cmd_force_divorce(message: Message):
    chat_id = message.chat.id
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer(f"💡 Формат: <code>{P}развести @user</code>", parse_mode="HTML")

    arg = parts[1].lstrip("@")
    target = await get_user(int(arg)) if arg.isdigit() else await get_user_by_username(arg)
    if not target:
        return await message.answer("❓ Юзер не найден.")

    marriage = await get_marriage(target["user_id"], chat_id)
    if not marriage:
        return await message.answer(f"💡 <b>{target['full_name']}</b> не в браке.", parse_mode="HTML")

    partner_id = marriage["user2_id"] if marriage["user1_id"] == target["user_id"] else marriage["user1_id"]

    # Нельзя развести с Анхой
    if partner_id == 0:
        return await message.answer("🖤 Этот брак нерушим.")

    partner = await get_user(partner_id)
    partner_name = partner["full_name"] if partner else f"id{partner_id}"

    await delete_marriage(target["user_id"], chat_id)
    await message.answer(
        f"⚖️ Модератор расторгает брак:\n"
        f"💔 <b>{target['full_name']}</b> & <b>{partner_name}</b>",
        parse_mode="HTML"
    )
