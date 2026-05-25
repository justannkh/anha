import random
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message
from typing import Callable, Dict, Any, Awaitable
from db.database import (
    upsert_user, get_user, get_role, set_role,
    increment_messages, update_balance,
)
from config import OWNER_ID, FRIEND_ID, BESTIE_ID, ALLOWED_GROUP_ID


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        chat = data.get("event_chat")
        user = data.get("event_from_user")

        if not user:
            return await handler(event, data)

        # Пропускаем только личку и разрешённые группы
        if chat is not None and chat.type not in ("private",):
            if chat.id not in ALLOWED_GROUP_ID:
                return

        await upsert_user(user.id, user.username or "", user.full_name)

        # Авто-роли для владельца и друга
        current_role = await get_role(user.id)
        if user.id == OWNER_ID and current_role != "owner":
            await set_role(user.id, "owner")
        elif user.id == FRIEND_ID and current_role not in ("owner", "friend"):
            await set_role(user.id, "friend")

        user_db = await get_user(user.id)
        data["user_db"] = user_db

        # Считаем сообщения + пассивный доход (1-3 монеты за сообщение)
        if isinstance(event, Message) and chat is not None and chat.type != "private":
            text = event.text or ""
            if not text.startswith(".") and not text.startswith("/"):
                await increment_messages(user.id)
                # Шанс 20% получить 1-2 монеты за обычное сообщение
                if random.random() < 0.20:
                    coins = random.randint(1, 2)
                    await update_balance(user.id, coins, "msg_reward", "За активность")

        return await handler(event, data)
