"""SQLite database for accounts, keywords, and seen tweets."""
import sqlite3
import os
from config import DB_PATH


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
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS seen_tweets (
            tweet_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            text TEXT,
            seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


# --- Accounts ---

def add_account(username: str) -> bool:
    """Add a Twitter account to monitor. Returns True if added, False if exists."""
    username = username.strip().lstrip("@").lower()
    conn = get_db()
    try:
        conn.execute("INSERT INTO accounts (username) VALUES (?)", (username,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def remove_account(username: str) -> bool:
    username = username.strip().lstrip("@").lower()
    conn = get_db()
    cur = conn.execute("DELETE FROM accounts WHERE username = ?", (username,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def list_accounts() -> list[str]:
    conn = get_db()
    rows = conn.execute("SELECT username FROM accounts ORDER BY id").fetchall()
    conn.close()
    return [r["username"] for r in rows]


# --- Keywords ---

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


def cleanup_old(days: int = 7):
    """Remove seen tweets older than N days."""
    conn = get_db()
    conn.execute(
        "DELETE FROM seen_tweets WHERE seen_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()
    conn.close()
