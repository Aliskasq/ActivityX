"""Configuration and environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "stepfun/step-2-16k")

# Twitter
TWITTER_LIST_ID = os.getenv("TWITTER_LIST_ID", "")
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.json")

# Schedule mode: "interval" (every N min) or "schedule" (specific MSK times)
SCHEDULE_TIMES_MSK = os.getenv("SCHEDULE_TIMES_MSK", "")  # e.g. "18:05,18:38,20:49,03:00"

# Runtime-mutable settings
_runtime = {
    "api_key": OPENROUTER_API_KEY,
    "model": OPENROUTER_MODEL,
    "schedule_mode": "schedule" if SCHEDULE_TIMES_MSK else "interval",  # "interval" or "schedule"
    "schedule_times": [t.strip() for t in SCHEDULE_TIMES_MSK.split(",") if t.strip()],
    "interval_min": 30,
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


def get_schedule_mode() -> str:
    return _runtime["schedule_mode"]


def get_schedule_times() -> list[str]:
    return _runtime["schedule_times"]


def get_interval_min() -> int:
    return _runtime["interval_min"]


def set_schedule_times(times: list[str]):
    _runtime["schedule_mode"] = "schedule"
    _runtime["schedule_times"] = times
    _save_env("SCHEDULE_TIMES_MSK", ",".join(times))


def set_interval_mode(minutes: int = 30):
    _runtime["schedule_mode"] = "interval"
    _runtime["interval_min"] = minutes
    _runtime["schedule_times"] = []
    _save_env("SCHEDULE_TIMES_MSK", "")


def _save_env(key: str, value: str):
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


# Monitoring
CHECK_INTERVAL_SEC = 1800  # 30 minutes
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "monitor.db")
