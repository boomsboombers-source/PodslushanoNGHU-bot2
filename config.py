import os

# ==============================================================================
# ================= НАСТРОЙКИ БОТА (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ) =======================
# ==============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit(
        "❌ BOT_TOKEN не задан. Установите переменную окружения BOT_TOKEN "
        "в панели Bothost (или в .env)."
    )

CHANNEL_ID = -1002304148771
LOG_CHAT_ID = -1004306176378
ADMIN_IDS = [1088467220, 1690346204]

WELCOME_IMAGE = os.path.join(BASE_DIR, "pictures", "Podslushano.png")

LOG_FILE = os.path.join(DATA_DIR, "messages.txt")
USERS_FILE = os.path.join(DATA_DIR, "users.txt")
SCHEDULE_FILE = os.path.join(DATA_DIR, "schedule.txt")
USERNAMES_FILE = os.path.join(DATA_DIR, "usernames.txt")
REPLIES_FILE = os.path.join(DATA_DIR, "replies.json")
MUTED_FILE = os.path.join(DATA_DIR, "muted.json")
DELAYED_FILE = os.path.join(DATA_DIR, "delayed.json")
SCHEDULE2_FILE = os.path.join(DATA_DIR, "schedule2.txt")
