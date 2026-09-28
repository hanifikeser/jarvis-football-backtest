import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
import imagehash


DB_PATH = Path("data/forward/jarvis_forward.db")

MAX_HOURS = 72
PHASH_MAX_DISTANCE = 8


def sha256_file(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


def parse_date(value):
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


def ensure_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_image_fingerprints_v2 (
            source_chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,

            sha256 TEXT NOT NULL,
            phash TEXT NOT NULL,
            dhash TEXT NOT NULL,

            width INTEGER,
            height INTEGER,
            aspect_ratio REAL,
            file_size INTEGER,

            PRIMARY KEY (
                source_chat_id,
                message_id
            )
        )
        """
    )

    conn.commit()


def build_fingerprints(conn):
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

    for index, (
        chat_id,
        message_id,
        media_path,
    ) in enumerate(rows, start=1):

        path = Path(media_path)

        if not path.exists():
            continue

        try:
            exact_hash = sha256_file(path)

            with Image.open(path) as img:
                img = img.convert("RGB")

                width, height = img.size

                ph = str(
                    imagehash.phash(img)
                )

                dh = str(
                    imagehash.dhash(img)
                )

            aspect_ratio = (
                width / height
                if height
                else 0
            )

            conn.execute(
                """
                INSERT INTO telegram_image_fingerprints_v2 (
                    source_chat_id,
                    message_id,
                    sha256,
                    phash,
                    dhash,
                    width,
                    height,
                    aspect_ratio,
                    file_size
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

                ON CONFLICT (
                    source_chat_id,
                    message_id
                )
                DO UPDATE SET
                    sha256 = excluded.sha256,
                    phash = excluded.phash,
                    dhash = excluded.dhash,
                    width = excluded.width,
                    height = excluded.height,
                    aspect_ratio =
                        excluded.aspect_ratio,
                    file_size =
                        excluded.file_size
                """,
                (
                    chat_id,
                    message_id,
                    exact_hash,
                    ph,
                    dh,
                    width,
                    height,
                    aspect_ratio,
                    path.stat().st_size,
                ),
            )

            if index % 100 == 0:
                print(
                    f"Fingerprint: "
                    f"{index}/{total}"
                )

        except Exception as e:
            print(
                f"[ERROR] "
                f"chat={chat_id} "
                f"message={message_id} "
                f"{e}"
            )

    conn.commit()


def exact_duplicate_report(conn):
    print()
    print("EXACT DUPLICATE GROUPS")
    print("=" * 70)

    groups = conn.execute(
        """
        SELECT
            sha256,
            COUNT(*) AS c
        FROM telegram_image_fingerprints_v2
        GROUP BY sha256
        HAVING COUNT(*) > 1
        ORDER BY c DESC
        """
    ).fetchall()

    duplicate_images = sum(
        count
        for _, count in groups
    )

    print(
        "Exact duplicate groups:",
        len(groups),
    )

    print(
        "Images inside duplicate groups:",
        duplicate_images,
    )

    print()

    for sha, count in groups[:20]:
        print(
            f"{sha[:12]}... "
            f"count={count}"
        )


def candidate_pairs(conn):
    rows = conn.execute(
        """
        SELECT
            f.source_chat_id,
            f.message_id,
            f.sha256,
            f.phash,
            f.width,
            f.height,
            f.aspect_ratio,
            m.received_at,
            m.source_chat_title,
            m.text

        FROM telegram_image_fingerprints_v2 f

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

    candidates = []

    for chat_id, items in by_chat.items():

        for i in range(len(items)):
            newer = items[i]

            newer_date = parse_date(
                newer[7]
            )

            newer_hash = (
                imagehash.hex_to_hash(
                    newer[3]
                )
            )

            for j in range(i - 1, -1, -1):
                older = items[j]

                older_date = parse_date(
                    older[7]
                )

                hours = (
                    newer_date - older_date
                ).total_seconds() / 3600

                if hours > MAX_HOURS:
                    break

                if hours < 0:
                    continue

                # Exact duplicate:
                # useful for repost detection,
                # not coupon-result inference.
                if newer[2] == older[2]:
                    continue

                # Different screenshot geometry
                # is less likely to be same coupon.
                ratio_gap = abs(
                    newer[6] - older[6]
                )

                if ratio_gap > 0.08:
                    continue

                older_hash = (
                    imagehash.hex_to_hash(
                        older[3]
                    )
                )

                distance = (
                    newer_hash
                    - older_hash
                )

                if (
                    distance
                    > PHASH_MAX_DISTANCE
                ):
                    continue

                size_ratio = (
                    min(
                        newer[4] * newer[5],
                        older[4] * older[5],
                    )
                    /
                    max(
                        newer[4] * newer[5],
                        older[4] * older[5],
                    )
                )

                if size_ratio < 0.70:
                    continue

                candidates.append(
                    {
                        "channel":
                            newer[8],
                        "older":
                            older[1],
                        "newer":
                            newer[1],
                        "hours":
                            round(hours, 2),
                        "distance":
                            distance,
                        "size_ratio":
                            round(
                                size_ratio,
                                3,
                            ),
                    }
                )

    candidates.sort(
        key=lambda x: (
            x["distance"],
            x["hours"],
        )
    )

    print()
    print("COUPON/RESULT CANDIDATE PAIRS")
    print("=" * 70)

    print(
        "Candidate pairs:",
        len(candidates),
    )

    print()

    for pair in candidates[:100]:
        print(
            f'{pair["channel"]} | '
            f'{pair["older"]} -> '
            f'{pair["newer"]} | '
            f'{pair["hours"]}h | '
            f'phash={pair["distance"]} | '
            f'size={pair["size_ratio"]}'
        )


def main():
    conn = sqlite3.connect(
        DB_PATH
    )

    ensure_table(conn)

    print()
    print(
        "JARVIS IMAGE "
        "FINGERPRINT V2"
    )

    print("=" * 70)

    build_fingerprints(conn)

    exact_duplicate_report(conn)

    candidate_pairs(conn)

    conn.close()


if __name__ == "__main__":
    main()