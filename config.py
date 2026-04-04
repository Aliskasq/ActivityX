"""Configuration and environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# OpenRouter (mutable at runtime via /key and /models)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "stepfun/step-2-16k")

# Runtime-mutable settings (updated via bot commands, saved to .env)
_runtime = {
    "api_key": OPENROUTER_API_KEY,
    "model": OPENROUTER_MODEL,
}


def get_api_key() -> str:
    return _runtime["api_key"]


def set_api_key(key: str):
    _runtime["api_key"] = key
    _save_env("OPENROUTER_API_KEY", key)


def get_model() -> str:
    return _runtime["model"]


def set_model(model: str):
    _runtime["model"] = model
    _save_env("OPENROUTER_MODEL", model)


def _save_env(key: str, value: str):
    """Update .env file so settings persist across restarts."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith(f"{key}="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)


# Nitter
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
]

# Monitoring
CHECK_INTERVAL_SEC = 300  # 5 minutes between checks (rotate accounts)
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "monitor.db")
