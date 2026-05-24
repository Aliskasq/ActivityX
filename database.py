"""SQLite database for accounts, per-account keywords/exclusions, and seen tweets."""
import logging
import sqlite3
import os
from config import DB_PATH

logger = logging.getLogger(__name__)


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            source TEXT DEFAULT 'manual',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS account_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            keyword TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(username, keyword)
        );
        CREATE TABLE IF NOT EXISTS account_exclusions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            word TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(username, word)
        );
        CREATE TABLE IF NOT EXISTS seen_tweets (
            tweet_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            text TEXT,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_ids (
            username TEXT PRIMARY KEY,
            rest_id TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    # Migration: add source column if missing
    cols = [r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()]
    if "source" not in cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN source TEXT DEFAULT 'manual'")
        conn.commit()
        logger.info("Migrated accounts table: added 'source' column")

    conn.close()


# --- Accounts ---

def add_account(username: str, source: str = "manual") -> bool:
    username = username.strip().lstrip("@").lower()
    conn = get_db()
    try:
        conn.execute("INSERT INTO accounts (username, source) VALUES (?, ?)", (username, source))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_account_source(username: str) -> str | None:
    username = username.strip().lstrip("@").lower()
    conn = get_db()
    row = conn.execute("SELECT source FROM accounts WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row["source"] if row else None


def remove_account(username: str) -> bool:
    username = username.strip().lstrip("@").lower()
    conn = get_db()
    cur = conn.execute("DELETE FROM accounts WHERE username = ?", (username,))
    conn.execute("DELETE FROM account_keywords WHERE username = ?", (username,))
    conn.execute("DELETE FROM account_exclusions WHERE username = ?", (username,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def list_accounts() -> list[str]:
    conn = get_db()
    rows = conn.execute("SELECT username FROM accounts ORDER BY id").fetchall()
    conn.close()
    return [r["username"] for r in rows]


# --- Global Keywords (fallback) ---

def add_keyword(word: str) -> bool:
    word = word.strip().lower()
    conn = get_db()
    try:
        conn.execute("INSERT INTO keywords (word) VALUES (?)", (word,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_keyword(word: str) -> bool:
    word = word.strip().lower()
    conn = get_db()
    cur = conn.execute("DELETE FROM keywords WHERE word = ?", (word,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def list_keywords() -> list[str]:
    conn = get_db()
    rows = conn.execute("SELECT word FROM keywords ORDER BY id").fetchall()
    conn.close()
    return [r["word"] for r in rows]


# --- Per-account Keywords ---

def add_account_keyword(username: str, keyword: str) -> bool:
    username = username.strip().lstrip("@").lower()
    keyword = keyword.strip().lower()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO account_keywords (username, keyword) VALUES (?, ?)",
            (username, keyword),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_account_keyword(username: str, keyword: str) -> bool:
    username = username.strip().lstrip("@").lower()
    keyword = keyword.strip().lower()
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM account_keywords WHERE username = ? AND keyword = ?",
        (username, keyword),
    )
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def list_account_keywords(username: str) -> list[str]:
    username = username.strip().lstrip("@").lower()
    conn = get_db()
    rows = conn.execute(
        "SELECT keyword FROM account_keywords WHERE username = ? ORDER BY id",
        (username,),
    ).fetchall()
    conn.close()
    return [r["keyword"] for r in rows]


# --- Per-account Exclusions ---

def add_account_exclusion(username: str, word: str) -> bool:
    username = username.strip().lstrip("@").lower()
    word = word.strip().lower()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO account_exclusions (username, word) VALUES (?, ?)",
            (username, word),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_account_exclusion(username: str, word: str) -> bool:
    username = username.strip().lstrip("@").lower()
    word = word.strip().lower()
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM account_exclusions WHERE username = ? AND word = ?",
        (username, word),
    )
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def list_account_exclusions(username: str) -> list[str]:
    username = username.strip().lstrip("@").lower()
    conn = get_db()
    rows = conn.execute(
        "SELECT word FROM account_exclusions WHERE username = ? ORDER BY id",
        (username,),
    ).fetchall()
    conn.close()
    return [r["word"] for r in rows]


# --- Seen tweets ---

def is_seen(tweet_id: str) -> bool:
    conn = get_db()
    row = conn.execute("SELECT 1 FROM seen_tweets WHERE tweet_id = ?", (tweet_id,)).fetchone()
    conn.close()
    return row is not None


def mark_seen(tweet_id: str, username: str, text: str):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO seen_tweets (tweet_id, username, text) VALUES (?, ?, ?)",
        (tweet_id, username, text),
    )
    conn.commit()
    conn.close()


# --- Settings (key-value) ---

def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_cached_user_id(username: str) -> str | None:
    """Get cached Twitter rest_id for a username."""
    username = username.strip().lstrip("@").lower()
    conn = get_db()
    row = conn.execute("SELECT rest_id FROM user_ids WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row["rest_id"] if row else None


def set_cached_user_id(username: str, rest_id: str):
    """Cache Twitter rest_id for a username."""
    username = username.strip().lstrip("@").lower()
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO user_ids (username, rest_id) VALUES (?, ?)",
        (username, rest_id),
    )
    conn.commit()
    conn.close()


def clear_seen() -> int:
    """Delete all seen tweets. Returns count deleted."""
    conn = get_db()
    cur = conn.execute("DELETE FROM seen_tweets")
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


def deduplicate_accounts():
    """Remove duplicate accounts (case-insensitive)."""
    conn = get_db()
    rows = conn.execute("SELECT id, username FROM accounts ORDER BY id").fetchall()
    seen = {}
    to_delete = []
    for r in rows:
        lower = r["username"].lower()
        if lower in seen:
            to_delete.append(r["id"])
        else:
            seen[lower] = r["id"]
    if to_delete:
        conn.execute(f"DELETE FROM accounts WHERE id IN ({','.join('?' * len(to_delete))})", to_delete)
        conn.commit()
        logger.info(f"Deduplicated {len(to_delete)} accounts")
    conn.close()


def cleanup_old(days: int = 7) -> int:
    """Delete seen tweets older than N days. Returns count deleted."""
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM seen_tweets WHERE seen_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


def seen_stats() -> list[dict]:
    """Per-account stats for seen tweets (total, matched/sent, last seen)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT 
            s.username,
            COUNT(*) as total,
            MIN(s.seen_at) as first_seen,
            MAX(s.seen_at) as last_seen
        FROM seen_tweets s
        GROUP BY s.username
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def seen_total() -> int:
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as cnt FROM seen_tweets").fetchone()
    conn.close()
    return row["cnt"]
