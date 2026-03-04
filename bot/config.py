import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
THENEWSAPI_KEY = os.getenv("THENEWSAPI_KEY")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bot.db")
LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "bot.log")
