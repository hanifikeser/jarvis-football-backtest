import asyncio
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError

DB_PATH = Path("data/forward/jarvis_forward.db")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(
            f"Missing required environment variable: {name}"
        )
    return value


def get_pending_photos():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            """
            SELECT
                source_chat_id,
                message_id,
                source_chat_title
            FROM telegram_messages
            WHERE media_type = 'photo'
              AND (
                    media_path IS NULL
                    OR media_path = ''
                  )
            ORDER BY received_at ASC
            """
        ).fetchall()


def update_media_path(
    chat_id,
    message_id,
    media_path,
):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            UPDATE telegram_messages
            SET media_path = ?
            WHERE source_chat_id = ?
              AND message_id = ?
            """,
            (
                media_path,
                chat_id,
                message_id,
            ),
        )

        conn.commit()


async def main():
    load_dotenv()

    api_id = int(
        require_env("TELEGRAM_API_ID")
    )

    api_hash = require_env(
        "TELEGRAM_API_HASH"
    )

    session_path = os.getenv(
        "TELEGRAM_SESSION",
        ".secrets/telegram/jarvis",
    )

    pending = get_pending_photos()

    print()
    print("JARVIS Telegram Photo Backfill")
    print("=" * 70)
    print(f"Pending photos: {len(pending)}")
    print()

    client = TelegramClient(
        session_path,
        api_id,
        api_hash,
    )

    await client.start()

    downloaded_count = 0
    failed_count = 0

    entity_cache = {}

    for index, (
        chat_id,
        message_id,
        chat_title,
    ) in enumerate(
        pending,
        start=1,
    ):
        try:
            if chat_id not in entity_cache:
                entity_cache[chat_id] = (
                    await client.get_entity(
                        chat_id
                    )
                )

            entity = entity_cache[chat_id]

            message = await client.get_messages(
                entity,
                ids=message_id,
            )

            if not message or not message.media:
                failed_count += 1
                continue

            media_dir = (
                Path("data/forward/media")
                / str(chat_id)
            )

            media_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            try:
                downloaded = await asyncio.wait_for(
                    message.download_media(
                        file=str(media_dir)
                    ),
                    timeout=60,
                )

            except asyncio.TimeoutError:
                print(
                    f"[TIMEOUT] "
                    f"{chat_title} | "
                    f"message={message_id}"
                )

                failed_count += 1
                continue

            if downloaded:
                update_media_path(
                    chat_id,
                    message_id,
                    str(downloaded),
                )

                downloaded_count += 1

            else:
                failed_count += 1

            if index % 50 == 0:
                print(
                    f"Progress: "
                    f"{index}/{len(pending)} | "
                    f"downloaded={downloaded_count} | "
                    f"failed={failed_count}"
                )

            await asyncio.sleep(0.15)

        except FloodWaitError as e:
            print(
                f"[FLOOD WAIT] "
                f"{e.seconds}s"
            )

            await asyncio.sleep(
                e.seconds + 1
            )

        except Exception as e:
            failed_count += 1

            print(
                f"[ERROR] "
                f"{chat_title} | "
                f"message={message_id} | "
                f"{type(e).__name__}: {e}"
            )

    print()
    print("=" * 70)
    print("PHOTO BACKFILL FINISHED")
    print(
        f"Downloaded: {downloaded_count}"
    )
    print(
        f"Failed: {failed_count}"
    )
    print("=" * 70)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())