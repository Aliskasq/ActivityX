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

# Runtime-mutable settings
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


def get_schedule_mode() -> str:
    from database import get_setting
    times = get_setting("schedule_times", "")
    return "schedule" if times else "interval"


def get_schedule_times() -> list[str]:
    from database import get_setting
    raw = get_setting("schedule_times", "")
    return [t.strip() for t in raw.split(",") if t.strip()] if raw else []


def get_interval_min() -> int:
    from database import get_setting
    return int(get_setting("interval_min", "20"))


def set_schedule_times(times: list[str]):
    from database import set_setting
    set_setting("schedule_times", ",".join(times))


def set_interval_mode(minutes: int = 20):
    from database import set_setting
    set_setting("schedule_times", "")
    set_setting("interval_min", str(minutes))


def get_sleep_window() -> tuple[str, str] | None:
    """Return (start, end) sleep times in HH:MM MSK, or None if not set."""
    from database import get_setting
    raw = get_setting("sleep_window", "")
    if not raw or raw == "0":
        return None
    parts = raw.split("-")
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


def set_sleep_window(start: str, end: str):
    from database import set_setting
    set_setting("sleep_window", f"{start}-{end}")


def clear_sleep_window():
    from database import set_setting
    set_setting("sleep_window", "0")


def get_scan_windows() -> list[tuple[str, str]]:
    """Return list of (start, end) scan windows in MSK, e.g. [('12:00','17:00'), ('21:00','02:00')]."""
    from database import get_setting
    raw = get_setting("scan_windows", "")
    if not raw:
        return []
    windows = []
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            s, e = part.split("-", 1)
            windows.append((s.strip(), e.strip()))
    return windows


def set_scan_windows(windows_str: str):
    from database import set_setting
    set_setting("scan_windows", windows_str)


def get_scan_period_min() -> int:
    from database import get_setting
    return int(get_setting("scan_period_min", "5"))


def set_scan_period_min(minutes: int):
    from database import set_setting
    set_setting("scan_period_min", str(minutes))


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
