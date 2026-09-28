import asyncio
import os
from collections import Counter
from datetime import timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from forward_store import init_db, save_message


def require_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise SystemExit(
            f"Missing required environment variable: {name}"
        )

    return value


def parse_chat_ids(value: str):
    ids = []

    for item in value.split(","):
        item = item.strip()

        if item:
            ids.append(int(item))

    return ids


def env_bool(name: str, default=False):
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_media_type(message):
    if message.photo:
        return "photo"

    if message.document:
        mime = (
            message.document.mime_type
            if message.document
            else None
        )

        return mime or "document"

    if message.media:
        return type(message.media).__name__

    return "none"


def should_download_media(message):
    if message.photo:
        return True

    if message.document:
        mime = (
            message.document.mime_type
            or ""
        )

        if mime.startswith("image/"):
            return True

    return False


async def main():
    load_dotenv()

    api_id = int(
        require_env("TELEGRAM_API_ID")
    )

    api_hash = require_env(
        "TELEGRAM_API_HASH"
    )

    target_chat_ids = parse_chat_ids(
        require_env(
            "TELEGRAM_TARGET_CHAT_IDS"
        )
    )

    backfill_limit = int(
        os.getenv(
            "TELEGRAM_BACKFILL_LIMIT",
            "3000",
        )
    )

    download_media = env_bool(
        "TELEGRAM_DOWNLOAD_MEDIA",
        False,
    )

    session_path = os.getenv(
        "TELEGRAM_SESSION",
        ".secrets/telegram/jarvis",
    )

    Path(session_path).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    init_db()

    client = TelegramClient(
        session_path,
        api_id,
        api_hash,
    )

    await client.start()

    print()
    print("JARVIS Telegram Deep Backfill")
    print("=" * 70)

    print(
        f"Message limit per channel: "
        f"{backfill_limit}"
    )

    print(
        f"Download images: "
        f"{download_media}"
    )

    total_processed = 0

    for chat_id in target_chat_ids:
        entity = await client.get_entity(
            chat_id
        )

        title = (
            getattr(entity, "title", None)
            or str(chat_id)
        )

        print()
        print("=" * 70)
        print(f"CHANNEL: {title}")
        print("=" * 70)

        count = 0
        media_counts = Counter()

        newest_date = None
        oldest_date = None

        try:
            async for message in client.iter_messages(
                entity,
                limit=backfill_limit,
            ):
                count += 1
                total_processed += 1

                if message.date:
                    message_date = (
                        message.date
                        .astimezone(timezone.utc)
                    )

                    if newest_date is None:
                        newest_date = message_date

                    oldest_date = message_date

                received_at = (
                    message.date.isoformat()
                    if message.date
                    else ""
                )

                text = (
                    message.raw_text
                    or message.message
                    or ""
                )

                media_type = get_media_type(
                    message
                )

                media_counts[
                    media_type
                ] += 1

                media_path = None

                if (
                    download_media
                    and message.media
                    and should_download_media(
                        message
                    )
                ):
                    media_dir = (
                        Path(
                            "data/forward/media"
                        )
                        / str(chat_id)
                    )

                    media_dir.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    try:
                        downloaded = (
                            await asyncio.wait_for(
                                message.download_media(
                                    file=str(
                                        media_dir
                                    )
                                ),
                                timeout=60,
                            )
                        )

                        if downloaded:
                            media_path = str(
                                downloaded
                            )

                    except asyncio.TimeoutError:
                        print(
                            f"[TIMEOUT] "
                            f"message={message.id}"
                        )

                    except FloodWaitError as e:
                        print(
                            f"[FLOOD WAIT] "
                            f"{e.seconds}s"
                        )

                        await asyncio.sleep(
                            e.seconds + 1
                        )

                save_message(
                    source_chat_id=chat_id,
                    source_chat_title=title,
                    message_id=message.id,
                    received_at=received_at,
                    sender_id=message.sender_id,
                    text=text,
                    media_type=media_type,
                    media_path=media_path,
                )

                if count % 100 == 0:
                    print(
                        f"Processed: "
                        f"{count}/"
                        f"{backfill_limit}"
                    )

        except FloodWaitError as e:
            print()
            print(
                f"Telegram requested "
                f"{e.seconds}s wait."
            )

            await asyncio.sleep(
                e.seconds + 1
            )

        print()
        print(
            f"Processed total: {count}"
        )

        if newest_date:
            print(
                "Newest message: "
                f"{newest_date.isoformat()}"
            )

        if oldest_date:
            print(
                "Oldest message: "
                f"{oldest_date.isoformat()}"
            )

        print()
        print("Media distribution:")

        for media_type, amount in (
            media_counts.most_common()
        ):
            print(
                f"  {media_type}: "
                f"{amount}"
            )

    print()
    print("=" * 70)

    print(
        "BACKFILL FINISHED"
    )

    print(
        f"Processed across all channels: "
        f"{total_processed}"
    )

    print("=" * 70)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())