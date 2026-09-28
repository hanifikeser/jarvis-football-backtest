import sqlite3
from pathlib import Path


DB_PATH = Path("data/forward/jarvis_forward.db")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_chat_id INTEGER NOT NULL,
                source_chat_title TEXT,
                message_id INTEGER NOT NULL,
                received_at TEXT NOT NULL,
                sender_id INTEGER,
                text TEXT,
                media_type TEXT,
                media_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_chat_id, message_id)
            )
            """
        )

        conn.commit()


def message_exists(source_chat_id, message_id):
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM telegram_messages
            WHERE source_chat_id = ?
              AND message_id = ?
            LIMIT 1
            """,
            (
                source_chat_id,
                message_id,
            ),
        ).fetchone()

        return row is not None


def save_message(
    source_chat_id,
    source_chat_title,
    message_id,
    received_at,
    sender_id=None,
    text=None,
    media_type=None,
    media_path=None,
):
    init_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO telegram_messages (
                source_chat_id,
                source_chat_title,
                message_id,
                received_at,
                sender_id,
                text,
                media_type,
                media_path
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(source_chat_id, message_id)
            DO UPDATE SET
                source_chat_title = excluded.source_chat_title,
                received_at = excluded.received_at,
                sender_id = excluded.sender_id,
                text = excluded.text,
                media_type = excluded.media_type,
                media_path = COALESCE(
                    excluded.media_path,
                    telegram_messages.media_path
                )
            """,
            (
                source_chat_id,
                source_chat_title,
                message_id,
                received_at,
                sender_id,
                text,
                media_type,
                media_path,
            ),
        )

        conn.commit()