import html
import sqlite3
from datetime import datetime
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageFilter,
    ImageOps,
    ImageStat,
)
import imagehash


DB_PATH = Path("data/forward/jarvis_forward.db")

REPORT_DIR = Path("reports")
REPORT_PATH = REPORT_DIR / "telegram_pair_review.html"

MAX_HOURS = 36
MAX_PAIRS = 200


def parse_date(value):
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


def visual_edge_distance(path_a, path_b):
    """
    Compare actual image content rather than only global layout.
    Text and markings create edges, so different coupons should
    separate more strongly than coupon/result variants.
    """

    with Image.open(path_a) as a:
        a = a.convert("L")

    with Image.open(path_b) as b:
        b = b.convert("L")

    size = (512, 512)

    a = ImageOps.fit(a, size)
    b = ImageOps.fit(b, size)

    # Ignore some static outer chrome/header/footer.
    crop = (40, 40, 472, 472)

    a = a.crop(crop)
    b = b.crop(crop)

    a = a.filter(ImageFilter.FIND_EDGES)
    b = b.filter(ImageFilter.FIND_EDGES)

    diff = ImageChops.difference(a, b)

    mean = ImageStat.Stat(diff).mean[0]

    return mean / 255.0


def classification_bonus(old_class, new_class):
    bonus = 0.0

    if old_class in {
        "COUPON",
        "UNKNOWN_IMAGE",
    }:
        bonus -= 1.0

    if new_class == "COUPON_RESULT":
        bonus -= 5.0

    if (
        old_class == "COUPON"
        and new_class == "COUPON_RESULT"
    ):
        bonus -= 5.0

    return bonus


def load_images(conn):
    return conn.execute(
        """
        SELECT
            f.source_chat_id,
            f.message_id,
            f.sha256,
            f.phash,
            f.aspect_ratio,

            m.received_at,
            m.source_chat_title,
            m.media_path,
            COALESCE(m.text, ''),

            COALESCE(
                c.final_class,
                c.predicted_class,
                'UNKNOWN'
            )

        FROM telegram_image_fingerprints_v2 f

        JOIN telegram_messages m
          ON m.source_chat_id = f.source_chat_id
         AND m.message_id = f.message_id

        LEFT JOIN telegram_classification c
          ON c.source_chat_id = f.source_chat_id
         AND c.message_id = f.message_id

        WHERE m.media_path IS NOT NULL

        ORDER BY
            f.source_chat_id,
            m.received_at
        """
    ).fetchall()


def build_candidates(rows):
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
                newer[5]
            )

            newer_path = Path(
                newer[7]
            )

            if not newer_path.exists():
                continue

            newer_phash = (
                imagehash.hex_to_hash(
                    newer[3]
                )
            )

            for j in range(i - 1, -1, -1):
                older = items[j]

                older_date = parse_date(
                    older[5]
                )

                hours = (
                    newer_date
                    - older_date
                ).total_seconds() / 3600

                if hours > MAX_HOURS:
                    break

                if hours < 0:
                    continue

                # Identical bytes = repost, not useful
                # as coupon/result inference.
                if newer[2] == older[2]:
                    continue

                ratio_gap = abs(
                    newer[4]
                    - older[4]
                )

                if ratio_gap > 0.05:
                    continue

                older_path = Path(
                    older[7]
                )

                if not older_path.exists():
                    continue

                older_phash = (
                    imagehash.hex_to_hash(
                        older[3]
                    )
                )

                phash_distance = (
                    newer_phash
                    - older_phash
                )

                # Global layout must still be
                # reasonably similar.
                if phash_distance > 10:
                    continue

                try:
                    edge_distance = (
                        visual_edge_distance(
                            older_path,
                            newer_path,
                        )
                    )

                except Exception:
                    continue

                old_class = older[9]
                new_class = newer[9]

                score = (
                    edge_distance * 100
                    + phash_distance * 1.25
                    + hours * 0.04
                    + classification_bonus(
                        old_class,
                        new_class,
                    )
                )

                candidates.append(
                    {
                        "channel":
                            newer[6],

                        "older_message":
                            older[1],

                        "newer_message":
                            newer[1],

                        "older_date":
                            older[5],

                        "newer_date":
                            newer[5],

                        "hours":
                            hours,

                        "phash":
                            phash_distance,

                        "edge":
                            edge_distance,

                        "score":
                            score,

                        "older_path":
                            older_path,

                        "newer_path":
                            newer_path,

                        "older_text":
                            older[8],

                        "newer_text":
                            newer[8],

                        "older_class":
                            old_class,

                        "newer_class":
                            new_class,
                    }
                )

    candidates.sort(
        key=lambda x: x["score"]
    )

    return candidates


def esc(value):
    return html.escape(
        str(value or "")
    )


def generate_html(candidates):
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    cards = []

    for index, pair in enumerate(
        candidates[:MAX_PAIRS],
        start=1,
    ):
        old_uri = (
            pair["older_path"]
            .resolve()
            .as_uri()
        )

        new_uri = (
            pair["newer_path"]
            .resolve()
            .as_uri()
        )

        cards.append(
            f"""
            <section class="pair">
                <h2>
                    #{index}
                    &nbsp; {esc(pair["channel"])}
                </h2>

                <div class="metrics">
                    score={pair["score"]:.3f}
                    &nbsp; | &nbsp;
                    edge={pair["edge"]:.4f}
                    &nbsp; | &nbsp;
                    phash={pair["phash"]}
                    &nbsp; | &nbsp;
                    gap={pair["hours"]:.2f}h
                </div>

                <div class="grid">

                    <div>
                        <h3>
                            BEFORE —
                            msg {pair["older_message"]}
                        </h3>

                        <p>
                            Class:
                            <strong>
                            {esc(pair["older_class"])}
                            </strong>
                        </p>

                        <p>
                            {esc(pair["older_date"])}
                        </p>

                        <img src="{old_uri}">

                        <pre>{esc(pair["older_text"])}</pre>
                    </div>

                    <div>
                        <h3>
                            AFTER —
                            msg {pair["newer_message"]}
                        </h3>

                        <p>
                            Class:
                            <strong>
                            {esc(pair["newer_class"])}
                            </strong>
                        </p>

                        <p>
                            {esc(pair["newer_date"])}
                        </p>

                        <img src="{new_uri}">

                        <pre>{esc(pair["newer_text"])}</pre>
                    </div>

                </div>
            </section>
            """
        )

    page = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="utf-8">
        <title>JARVIS Telegram Pair Review</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 1500px;
                margin: 20px auto;
                background: #111;
                color: #eee;
            }}

            .pair {{
                padding: 20px;
                margin-bottom: 35px;
                border: 1px solid #444;
                border-radius: 12px;
                background: #181818;
            }}

            .grid {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
            }}

            img {{
                max-width: 100%;
                max-height: 850px;
                object-fit: contain;
                background: #000;
            }}

            pre {{
                white-space: pre-wrap;
                word-break: break-word;
                background: #222;
                padding: 10px;
            }}

            .metrics {{
                margin-bottom: 15px;
                color: #bbb;
            }}
        </style>
    </head>

    <body>

        <h1>
            JARVIS Telegram Coupon / Result Review
        </h1>

        <p>
            Candidate pairs shown:
            {min(len(candidates), MAX_PAIRS)}
            / {len(candidates)}
        </p>

        {''.join(cards)}

    </body>
    </html>
    """

    REPORT_PATH.write_text(
        page,
        encoding="utf-8",
    )


def main():
    conn = sqlite3.connect(
        DB_PATH
    )

    rows = load_images(
        conn
    )

    candidates = build_candidates(
        rows
    )

    generate_html(
        candidates
    )

    conn.close()

    print()
    print(
        "JARVIS PAIR REVIEW V3"
    )
    print("=" * 70)

    print(
        "Images analyzed:",
        len(rows),
    )

    print(
        "Candidate pairs:",
        len(candidates),
    )

    print(
        "Review pairs:",
        min(
            len(candidates),
            MAX_PAIRS,
        ),
    )

    print(
        "Report:",
        REPORT_PATH,
    )


if __name__ == "__main__":
    main()