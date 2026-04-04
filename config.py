"""Configuration and environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")  # default chat to post to
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

# Nitter
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
]

# Monitoring
CHECK_INTERVAL_SEC = 60  # 1 minute between checks (rotate accounts)
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "monitor.db")
