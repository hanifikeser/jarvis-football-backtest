import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events

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

    if not ids:
        raise SystemExit(
            "TELEGRAM_TARGET_CHAT_IDS contains no chat IDs"
        )

    return ids


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

    return None


async def main():
    load_dotenv()

    api_id = int(
        require_env("TELEGRAM_API_ID")
    )

    api_hash = require_env(
        "TELEGRAM_API_HASH"
    )

    target_chat_ids = parse_chat_ids(
        require_env("TELEGRAM_TARGET_CHAT_IDS")
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
    print("JARVIS Telegram Listener started.")
    print("Watching chats:")

    for chat_id in target_chat_ids:
        print(f"  - {chat_id}")

    print()
    print("Waiting for new messages...")
    print("Press CTRL+C to stop.")
    print()

    @client.on(
        events.NewMessage(
            chats=target_chat_ids
        )
    )
    async def handler(event):
        message = event.message

        chat = await event.get_chat()

        chat_title = (
            getattr(chat, "title", None)
            or str(event.chat_id)
        )

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

        media_path = None

        if message.media:
            media_dir = (
                Path("data/forward/media")
                / str(event.chat_id)
            )

            media_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            downloaded = await message.download_media(
                file=str(media_dir)
            )

            if downloaded:
                media_path = str(downloaded)

        save_message(
            source_chat_id=event.chat_id,
            source_chat_title=chat_title,
            message_id=message.id,
            received_at=received_at,
            sender_id=event.sender_id,
            text=text,
            media_type=media_type,
            media_path=media_path,
        )

        print(
            f"[NEW] "
            f"{chat_title} | "
            f"message={message.id} | "
            f"media={media_type or 'none'}"
        )

    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
        print("JARVIS Telegram Listener stopped.")