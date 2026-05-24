import inspect
from functools import wraps
from aiogram.types import Message
from db.database import get_role, ROLES

CMD_PREFIX = "."


def require_role(min_role: str):
    """
    Декоратор для хэндлеров — проверяет минимально допустимую роль.
    Прокидывает только те kwargs, которые ожидает функция.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(message: Message, **kwargs):
            role = await get_role(message.from_user.id)
            if ROLES.get(role, 99) > ROLES.get(min_role, 99):
                await message.answer(
                    f"\u26d4 Эта команда только для {min_role}+."
                )
                return
            sig_params = inspect.signature(func).parameters
            filtered = {k: v for k, v in kwargs.items() if k in sig_params}
            return await func(message, **filtered)
        return wrapper
    return decorator


def owner_only(func):
    return require_role("owner")(func)

def friend_only(func):
    return require_role("friend")(func)

def admin_only(func):
    return require_role("admin")(func)

def moder_only(func):
    return require_role("moder")(func)
