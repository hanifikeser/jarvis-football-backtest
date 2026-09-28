import sqlite3
from pathlib import Path

from PIL import Image
import imagehash


DB_PATH = Path("data/forward/jarvis_forward.db")


def ensure_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_image_fingerprints (
            source_chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            phash TEXT NOT NULL,
            dhash TEXT NOT NULL,
            width INTEGER,
            height INTEGER,
            file_size INTEGER,
            PRIMARY KEY (
                source_chat_id,
                message_id
            )
        )
        """
    )
    conn.commit()


def build_hashes(conn):
    rows = conn.execute(
        """
        SELECT
            source_chat_id,
            message_id,
            media_path
        FROM telegram_messages
        WHERE media_type = 'photo'
          AND media_path IS NOT NULL
        """
    ).fetchall()

    total = len(rows)
    done = 0
    failed = 0

    for chat_id, message_id, media_path in rows:
        path = Path(media_path)

        if not path.exists():
            failed += 1
            continue

        try:
            with Image.open(path) as img:
                img = img.convert("RGB")

                ph = str(
                    imagehash.phash(img)
                )

                dh = str(
                    imagehash.dhash(img)
                )

                width, height = img.size

            conn.execute(
                """
                INSERT INTO telegram_image_fingerprints (
                    source_chat_id,
                    message_id,
                    phash,
                    dhash,
                    width,
                    height,
                    file_size
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)

                ON CONFLICT (
                    source_chat_id,
                    message_id
                )
                DO UPDATE SET
                    phash = excluded.phash,
                    dhash = excluded.dhash,
                    width = excluded.width,
                    height = excluded.height,
                    file_size = excluded.file_size
                """,
                (
                    chat_id,
                    message_id,
                    ph,
                    dh,
                    width,
                    height,
                    path.stat().st_size,
                ),
            )

            done += 1

            if done % 100 == 0:
                print(
                    f"Hashed: {done}/{total}"
                )

        except Exception as e:
            failed += 1

            print(
                f"[ERROR] "
                f"chat={chat_id} "
                f"message={message_id} "
                f"{type(e).__name__}: {e}"
            )

    conn.commit()

    print()
    print("IMAGE HASHING FINISHED")
    print("=" * 60)
    print("Total photos:", total)
    print("Hashed:", done)
    print("Failed:", failed)


def find_near_duplicates(conn):
    rows = conn.execute(
        """
        SELECT
            f.source_chat_id,
            f.message_id,
            f.phash,
            m.received_at,
            m.source_chat_title
        FROM telegram_image_fingerprints f
        JOIN telegram_messages m
          ON m.source_chat_id =
             f.source_chat_id
         AND m.message_id =
             f.message_id
        ORDER BY
            f.source_chat_id,
            m.received_at
        """
    ).fetchall()

    by_chat = {}

    for row in rows:
        by_chat.setdefault(
            row[0],
            [],
        ).append(row)

    strong = []
    likely = []
    weak = []

    for chat_id, items in by_chat.items():
        for i in range(len(items)):
            current = items[i]

            current_hash = (
                imagehash.hex_to_hash(
                    current[2]
                )
            )

            # Compare only recent previous images.
            # Enough for repost/result detection.
            start = max(
                0,
                i - 250,
            )

            for j in range(start, i):
                previous = items[j]

                previous_hash = (
                    imagehash.hex_to_hash(
                        previous[2]
                    )
                )

                distance = (
                    current_hash
                    - previous_hash
                )

                pair = {
                    "channel":
                        current[4],
                    "older_message":
                        previous[1],
                    "newer_message":
                        current[1],
                    "distance":
                        distance,
                    "older_date":
                        previous[3],
                    "newer_date":
                        current[3],
                }

                if distance <= 4:
                    strong.append(pair)

                elif distance <= 8:
                    likely.append(pair)

                elif distance <= 12:
                    weak.append(pair)

    print()
    print("NEAR-DUPLICATE REPORT")
    print("=" * 60)

    print(
        "Strong pairs (0-4):",
        len(strong),
    )

    print(
        "Likely pairs (5-8):",
        len(likely),
    )

    print(
        "Weak pairs (9-12):",
        len(weak),
    )

    print()
    print("TOP STRONG / LIKELY PAIRS")
    print("-" * 60)

    candidates = sorted(
        strong + likely,
        key=lambda x: x["distance"],
    )

    for pair in candidates[:50]:
        print(
            f'{pair["channel"]} | '
            f'{pair["older_message"]} -> '
            f'{pair["newer_message"]} | '
            f'distance={pair["distance"]}'
        )


def main():
    conn = sqlite3.connect(
        DB_PATH
    )

    ensure_table(conn)

    build_hashes(conn)

    find_near_duplicates(conn)

    conn.close()


if __name__ == "__main__":
    main()