import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, utils


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


async def main():
    load_dotenv()

    api_id = int(require_env("TELEGRAM_API_ID"))
    api_hash = require_env("TELEGRAM_API_HASH")

    session_path = os.getenv(
        "TELEGRAM_SESSION",
        ".secrets/telegram/jarvis",
    )

    phone = os.getenv("TELEGRAM_PHONE") or None

    Path(session_path).parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    client = TelegramClient(
        session_path,
        api_id,
        api_hash,
    )

    await client.start(phone=phone)

    print()
    print("Telegram connection successful.")
    print()
    print("Available groups / channels:")
    print("-" * 80)

    dialogs = await client.get_dialogs()

    found = 0

    for dialog in dialogs:
        if not (dialog.is_group or dialog.is_channel):
            continue

        found += 1

        chat_id = utils.get_peer_id(dialog.entity)

        title = (
            getattr(dialog.entity, "title", None)
            or dialog.name
            or "Unnamed"
        )

        kind = "GROUP" if dialog.is_group else "CHANNEL"

        print(
            f"{found:03d} | "
            f"{kind:7s} | "
            f"chat_id={chat_id} | "
            f"{title}"
        )

    print("-" * 80)
    print(f"Found: {found}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())