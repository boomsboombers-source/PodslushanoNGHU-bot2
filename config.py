import os

# ==============================================================================
# ================= НАСТРОЙКИ БОТА (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ) =======================
# ==============================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL_ID = -1002304148771
LOG_CHAT_ID = -1004306176378

ADMIN_IDS = [1088467220, 1690346204]

WELCOME_IMAGE = "pictures/Podslushano.png"

# Пути к файлам для хранения данных
LOG_FILE = "data/messages.txt"
USERS_FILE = "data/users.txt"
SCHEDULE_FILE = "data/schedule.txt"
USERNAMES_FILE = "data/usernames.txt"
REPLIES_FILE = "data/replies.json"
MUTED_FILE = "data/muted.json"
DELAYED_FILE = "data/delayed.json"