from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEYS = [k.strip() for k in os.getenv("GROQ_API_KEY", os.getenv("GROQ_API_KEYS", "")).split(",") if k.strip()]

_owner_id = os.getenv("OWNER_ID")
if not _owner_id:
    raise ValueError("OWNER_ID не задан в .env — укажи Telegram ID владельца.")
OWNER_ID = int(_owner_id)

FRIEND_ID          = int(os.getenv("FRIEND_ID", "0"))
BESTIE_ID          = int(os.getenv("BESTIE_ID", "1824278671"))

_group_id_raw = os.getenv("ALLOWED_GROUP_ID", "")
if not _group_id_raw:
    raise ValueError("ALLOWED_GROUP_ID не задан в .env")

ALLOWED_GROUP_ID = [int(i.strip()) for i in _group_id_raw.split(",") if i.strip()]

PUBLISH_CHANNEL_ID = int(os.getenv("PUBLISH_CHANNEL_ID", "0"))
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")

# Ссылки для команды .ссылки
LINK_TG_CHANNEL = os.getenv("LINK_TG_CHANNEL", "")
LINK_BOOSTI     = os.getenv("LINK_BOOSTI",     "")
LINK_ARCHIVE    = os.getenv("LINK_ARCHIVE",    "")
LINK_YOUTUBE_CH = os.getenv("LINK_YOUTUBE_CH", "")

# Экономика
DAILY_REWARD       = int(os.getenv("DAILY_REWARD", "200"))
DAILY_REWARD_STREAK = int(os.getenv("DAILY_REWARD_STREAK", "50"))  # бонус за серию
CASINO_MIN_BET     = int(os.getenv("CASINO_MIN_BET", "10"))
CASINO_MAX_BET     = int(os.getenv("CASINO_MAX_BET", "5000"))

# Магазин — ссылки на товары
SHOP_BOOSTI_URL    = os.getenv("SHOP_BOOSTI_URL", "")
