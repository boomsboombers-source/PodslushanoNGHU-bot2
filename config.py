import os
from datetime import datetime
from dotenv import load_dotenv

# ==============================================================================
# ================= НАСТРОЙКИ БОТА (МЕНЯТЬ ТОЛЬКО ЗДЕСЬ) =======================
# ==============================================================================
# Загружаем переменные из файла .env (если он есть)
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Теперь токен подтянется либо из .env, либо из настроек Bothost
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit(
        "❌ BOT_TOKEN не задан. Установите переменную окружения BOT_TOKEN "
        "в панели Bothost (или в .env)."
    )

CHANNEL_ID = -1002304148771
LOG_CHAT_ID = -1004306176378

ADMIN_IDS = [1088467220, 1690346204] # <-- ID АДМИНОВ
#Я, Дима
MODERATOR_IDS = [5904499737, 1709229252, 1668329260] # <-- ID модераторов
#Кирилл, Маша Х, Макс К.

# Объединенный список для проверок (Админы + Модераторы)
STAFF_IDS = ADMIN_IDS + MODERATOR_IDS

WELCOME_IMAGE = os.path.join(BASE_DIR, "pictures", "Podslushano.png")

USERS_FILE = os.path.join(DATA_DIR, "users.txt")
SCHEDULE_FILE = os.path.join(DATA_DIR, "schedule.txt")
REPLIES_FILE = os.path.join(DATA_DIR, "replies.json")
MUTED_FILE = os.path.join(DATA_DIR, "muted.json")
DELAYED_FILE = os.path.join(DATA_DIR, "delayed.json")
SCHEDULE2_FILE = os.path.join(DATA_DIR, "schedule2.txt")


# ==============================================================================
# ================= СЕЗОННЫЕ ЭМОДЗИ (ДИНАМИЧЕСКИЕ) =============================
# ==============================================================================

# Если нужно принудительно сменить тему (для тестов), сюда пишется название темы.
# В обычном режиме здесь None.
FORCE_THEME = None

def get_current_theme() -> str:
    """Определяет тему оформления по дате (или принудительно)."""
    global FORCE_THEME
    if FORCE_THEME:
        return FORCE_THEME
        
    now = datetime.now()
    m, d = now.month, now.day

    if m == 12 or (m == 1 and d <= 14): return "new_year"
    if m == 2 and 13 <= d <= 15: return "valentine"
    if m == 2 and 22 <= d <= 24: return "defender"
    if m == 3 and 7 <= d <= 9: return "march_8"
    if (m == 4 and d >= 30) or (m == 5 and d <= 2): return "may_day"
    if m in (6, 7, 8): return "summer"
    if (m == 8 and d == 31) or (m == 9 and d <= 2): return "knowledge_day"
    if (m == 10 and d >= 28) or (m == 11 and d == 1): return "halloween"
    return "default"

def get_theme() -> dict:
    """Возвращает актуальный словарь эмодзи."""
    return THEMES[get_current_theme()]

THEMES = {
    "new_year": {
        "hi": "🎅", "calendar": "❄️", "doc": "🎁", "ok": "🎄", "cancel": "❄️", "fire": "✨", "star": "⭐",
        "greeting": "С наступающим Новым годом! Пусть желания сбудутся!",
        "sent_text": "🎄 Твоя анонимка улетела в канал! С наступающим!",
        "reply_text": "🎁 Твой ответ опубликован! Пусть праздник будет волшебным!"
    },
    "valentine": {
        "hi": "💘", "calendar": "💌", "doc": "🌹", "ok": "💖", "cancel": "💔", "fire": "❤️‍🔥", "star": "💕",
        "greeting": "С Днем всех влюбленных! Любви и тепла!",
        "sent_text": "💌 Твоя анонимка отправлена! Надеемся, она про любовь!",
        "reply_text": "💖 Твой ответ опубликован. Пусть будет больше нежности!"
    },
    "defender": {
        "hi": "🎖", "calendar": "🪖", "doc": "⭐", "ok": "🎗", "cancel": "🛑", "fire": "💥", "star": "🎖",
        "greeting": "С Днем защитника Отечества! Силы и мужества!",
        "sent_text": "🎖 Анонимка отправлена! С праздником, защитники!",
        "reply_text": "🎗 Твой ответ в канале. Парни, с 23 февраля!"
    },
    "march_8": {
        "hi": "🌷", "calendar": "🌸", "doc": "💐", "ok": "🌺", "cancel": "🥀", "fire": "🌼", "star": "💮",
        "greeting": "С 8 Марта! Весны, цветов и хорошего настроения!",
        "sent_text": "🌷 Твоя анонимка отправлена! С праздником весны!",
        "reply_text": "🌸 Твой ответ опубликован. Девушки, с 8 Марта!"
    },
    "may_day": {
        "hi": "🌱", "calendar": "🌿", "doc": "🍃", "ok": "🌞", "cancel": "🌧", "fire": "🌻", "star": "🍀",
        "greeting": "С 1 Мая! Мира, труда и весеннего солнца!",
        "sent_text": "🌱 Анонимка отправлена! С Праздником весны и труда!",
        "reply_text": "🌿 Твой ответ в канале. С 1 Мая!"
    },
    "summer": {
        "hi": "☀️", "calendar": "🏖", "doc": "🍦", "ok": "🌴", "cancel": "🌧", "fire": "🍉", "star": "🕶",
        "greeting": "Лето в разгаре! Отдыхай, но не забывай про канал!",
        "sent_text": "☀️ Анонимка улетела в канал. Хорошего лета!",
        "reply_text": "🌴 Твой ответ опубликован. Отдыхай!"
    },
    "knowledge_day": {
        "hi": "🎒", "calendar": "🍁", "doc": "📚", "ok": "🔔", "cancel": "✏️", "fire": "📖", "star": "🎓",
        "greeting": "С Днем знаний! Успехов в учебе и новых открытий!",
        "sent_text": "🔔 Твоя анонимка отправлена. С 1 Сентября!",
        "reply_text": "📚 Твой ответ опубликован. Знания — сила!"
    },
    "halloween": {
        "hi": "🎃", "calendar": "🕷", "doc": "👻", "ok": "🕸", "cancel": "💀", "fire": "🔥", "star": "🦇",
        "greeting": "Хэллоуин! Берегись призраков и нечисти!",
        "sent_text": "🕸 Твоя анонимка улетела в канал... Надеемся, она не слишком страшная!",
        "reply_text": "🦇 Твой ответ опубликован. Не пугай людей!"
    },
    "default": {
        "hi": "👋", "calendar": "📅", "doc": "📋", "ok": "✅", "cancel": "❌", "fire": "🔥", "star": "⭐",
        "greeting": "Этот бот — официальный анонимный канал связи с <b>Подслушано НГХУ</b>.",
        "sent_text": "Сообщение отправлено в канал анонимно.",
        "reply_text": "Твой ответ опубликован в канале!"
    }
}
