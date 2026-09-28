import csv
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


DB_PATH = Path(
    "data/forward/jarvis_forward.db"
)

REPORT_DIR = Path("reports")

ISTANBUL = ZoneInfo(
    "Europe/Istanbul"
)


def normalize_text(value):
    if not value:
        return ""

    replacements = {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }

    value = str(value)

    for old, new in replacements.items():
        value = value.replace(
            old,
            new,
        )

    return value.lower()


def parse_iso(value):
    if not value:
        return None

    dt = datetime.fromisoformat(
        value.replace(
            "Z",
            "+00:00",
        )
    )

    return dt


def to_istanbul(value):
    dt = parse_iso(value)

    if dt is None:
        return None

    return dt.astimezone(
        ISTANBUL
    )


def extract_coupon_date(text):
    """
    Example:
    {18.08.2026}
    """

    match = re.search(
        r"[\{\[]?"
        r"(\d{1,2})\."
        r"(\d{1,2})\."
        r"(\d{4})"
        r"[\}\]]?",
        text,
    )

    if not match:
        return None

    day = int(
        match.group(1)
    )

    month = int(
        match.group(2)
    )

    year = int(
        match.group(3)
    )

    try:
        return datetime(
            year,
            month,
            day,
            tzinfo=ISTANBUL,
        ).date()

    except ValueError:
        return None


def extract_start_time(text):
    normalized = normalize_text(
        text
    )

    patterns = [
        r"baslama\s+saatleri?\s*[:\-]\s*(\d{1,2}:\d{2})",
        r"baslama\s+saati\s*[:\-]\s*(\d{1,2}:\d{2})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            normalized,
        )

        if match:
            return match.group(1)

    return None


def extract_advertised_odds(text):
    """
    Examples:
    +325 ORAN
    +3.25 ORAN
    3,25 ORAN
    """

    normalized = normalize_text(
        text
    )

    match = re.search(
        r"\+\s*(\d{2,4})\s*oran",
        normalized,
    )

    if match:
        return "+" + match.group(1)

    match = re.search(
        r"(\d+[.,]\d+)\s*oran",
        normalized,
    )

    if match:
        return (
            match.group(1)
            .replace(",", ".")
        )

    return None


def clean_match_line(line):
    line = line.strip()

    prefixes = [
        "➡️",
        "➡",
        "➜",
        "➤",
        "▶️",
        "▶",
        "►",
        "•",
        "-",
    ]

    changed = True

    while changed:
        changed = False

        for prefix in prefixes:
            if line.startswith(
                prefix
            ):
                line = (
                    line[
                        len(prefix):
                    ]
                    .strip()
                )

                changed = True

    return line


def looks_like_match(line):
    normalized = normalize_text(
        line
    )

    blocked = [
        "gunun maclari",
        "baslama saat",
        "iletisim",
        "oran",
        "kupon",
        "firsat",
        "analiz",
    ]

    if any(
        word in normalized
        for word in blocked
    ):
        return False

    if " - " not in line:
        return False

    parts = line.split(
        " - ",
        1,
    )

    if len(parts) != 2:
        return False

    home = parts[0].strip()
    away = parts[1].strip()

    if len(home) < 2:
        return False

    if len(away) < 2:
        return False

    return True


def extract_matches(text):
    matches = []

    for raw_line in text.splitlines():
        line = clean_match_line(
            raw_line
        )

        if not looks_like_match(
            line
        ):
            continue

        home, away = line.split(
            " - ",
            1,
        )

        matches.append(
            {
                "home_team":
                    home.strip(),

                "away_team":
                    away.strip(),
            }
        )

    return matches


def ensure_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS karaca_coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            source_chat_id INTEGER NOT NULL,
            primary_message_id INTEGER NOT NULL UNIQUE,

            telegram_received_at TEXT,

            coupon_date TEXT,
            start_time TEXT,
            advertised_odds TEXT,

            raw_caption TEXT,

            match_count INTEGER DEFAULT 0,

            claimed_result TEXT,
            claimed_result_message_id INTEGER,
            claimed_result_received_at TEXT,

            result_link_confidence TEXT,

            verified_result TEXT,
            verification_status TEXT DEFAULT 'UNVERIFIED',

            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS karaca_coupon_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            coupon_id INTEGER NOT NULL,

            selection_order INTEGER NOT NULL,

            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,

            visible_market TEXT,
            visible_selection TEXT,

            hidden_prediction TEXT,
            hidden_confidence REAL,

            actual_hidden_selection TEXT,

            match_result TEXT,
            prediction_correct INTEGER,

            FOREIGN KEY (
                coupon_id
            )
            REFERENCES karaca_coupons(id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS karaca_coupon_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            coupon_id INTEGER NOT NULL,

            linked_message_id INTEGER NOT NULL,

            link_type TEXT NOT NULL,

            confidence TEXT,

            hours_after_primary REAL,

            UNIQUE(
                coupon_id,
                linked_message_id,
                link_type
            ),

            FOREIGN KEY (
                coupon_id
            )
            REFERENCES karaca_coupons(id)
        )
        """
    )

    conn.commit()


def clear_generated_data(conn):
    """
    Rebuild parser output safely.

    This does NOT delete Telegram raw data.
    """

    conn.execute(
        """
        DELETE FROM karaca_coupon_links
        """
    )

    conn.execute(
        """
        DELETE FROM karaca_coupon_matches
        """
    )

    conn.execute(
        """
        DELETE FROM karaca_coupons
        """
    )

    conn.commit()


def load_karaca_messages(conn):
    return conn.execute(
        """
        SELECT
            m.source_chat_id,
            m.source_chat_title,
            m.message_id,
            m.received_at,
            COALESCE(m.text, ''),
            m.media_path,

            COALESCE(
                c.final_class,
                c.predicted_class,
                'UNKNOWN'
            ) AS class_name

        FROM telegram_messages m

        LEFT JOIN telegram_classification c
          ON c.source_chat_id =
             m.source_chat_id

         AND c.message_id =
             m.message_id

        WHERE lower(
            m.source_chat_title
        ) LIKE '%karaca%'

        ORDER BY m.received_at
        """
    ).fetchall()


def insert_primary_coupons(
    conn,
    messages,
):
    primary_count = 0
    parsed_match_count = 0
    empty_coupon_count = 0

    for row in messages:
        (
            chat_id,
            chat_title,
            message_id,
            received_at,
            text,
            media_path,
            class_name,
        ) = row

        if (
            class_name
            != "COUPON_PRIMARY"
        ):
            continue

        coupon_date = (
            extract_coupon_date(
                text
            )
        )

        if coupon_date is None:
            local_dt = to_istanbul(
                received_at
            )

            coupon_date = (
                local_dt.date()
                if local_dt
                else None
            )

        start_time = (
            extract_start_time(
                text
            )
        )

        advertised_odds = (
            extract_advertised_odds(
                text
            )
        )

        matches = extract_matches(
            text
        )

        cursor = conn.execute(
            """
            INSERT INTO karaca_coupons (
                source_chat_id,
                primary_message_id,
                telegram_received_at,

                coupon_date,
                start_time,
                advertised_odds,

                raw_caption,
                match_count
            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                message_id,
                received_at,

                (
                    str(coupon_date)
                    if coupon_date
                    else None
                ),

                start_time,
                advertised_odds,

                text,
                len(matches),
            ),
        )

        coupon_id = (
            cursor.lastrowid
        )

        for index, match in enumerate(
            matches,
            start=1,
        ):
            conn.execute(
                """
                INSERT INTO karaca_coupon_matches (
                    coupon_id,
                    selection_order,
                    home_team,
                    away_team
                )

                VALUES (?, ?, ?, ?)
                """,
                (
                    coupon_id,
                    index,

                    match[
                        "home_team"
                    ],

                    match[
                        "away_team"
                    ],
                ),
            )

            parsed_match_count += 1

        primary_count += 1

        if not matches:
            empty_coupon_count += 1

    conn.commit()

    return (
        primary_count,
        parsed_match_count,
        empty_coupon_count,
    )


def get_coupon_candidates(
    conn,
    chat_id,
):
    return conn.execute(
        """
        SELECT
            id,
            primary_message_id,
            telegram_received_at,
            coupon_date

        FROM karaca_coupons

        WHERE source_chat_id = ?

        ORDER BY
            telegram_received_at
        """,
        (
            chat_id,
        ),
    ).fetchall()


def find_best_previous_coupon(
    coupons,
    message_received_at,
    max_hours=36,
):
    message_dt = parse_iso(
        message_received_at
    )

    if message_dt is None:
        return None

    valid = []

    for coupon in coupons:
        (
            coupon_id,
            primary_message_id,
            coupon_received_at,
            coupon_date,
        ) = coupon

        coupon_dt = parse_iso(
            coupon_received_at
        )

        if coupon_dt is None:
            continue

        delta = (
            message_dt
            - coupon_dt
        )

        hours = (
            delta.total_seconds()
            / 3600
        )

        if hours < 0:
            continue

        if hours > max_hours:
            continue

        same_local_date = (
            message_dt
            .astimezone(
                ISTANBUL
            )
            .date()
            ==
            coupon_dt
            .astimezone(
                ISTANBUL
            )
            .date()
        )

        valid.append(
            {
                "coupon_id":
                    coupon_id,

                "primary_message_id":
                    primary_message_id,

                "hours":
                    hours,

                "same_local_date":
                    same_local_date,
            }
        )

    if not valid:
        return None

    same_day = [
        item
        for item in valid
        if item[
            "same_local_date"
        ]
    ]

    pool = (
        same_day
        if same_day
        else valid
    )

    pool.sort(
        key=lambda x:
            x["hours"]
    )

    best = pool[0]

    if (
        best["same_local_date"]
        and best["hours"] <= 12
    ):
        confidence = "HIGH"

    elif (
        best["same_local_date"]
    ):
        confidence = "MEDIUM"

    else:
        confidence = "LOW"

    best[
        "confidence"
    ] = confidence

    return best


def link_promos_and_results(
    conn,
    messages,
):
    chats = sorted(
        {
            row[0]
            for row in messages
        }
    )

    coupon_cache = {
        chat_id:
            get_coupon_candidates(
                conn,
                chat_id,
            )
        for chat_id in chats
    }

    promo_linked = 0
    promo_unlinked = 0

    result_linked = 0
    result_unlinked = 0

    for row in messages:
        (
            chat_id,
            chat_title,
            message_id,
            received_at,
            text,
            media_path,
            class_name,
        ) = row

        if class_name not in {
            "COUPON_PROMO",
            "COUPON_RESULT",
        }:
            continue

        best = (
            find_best_previous_coupon(
                coupon_cache.get(
                    chat_id,
                    [],
                ),
                received_at,
            )
        )

        if best is None:
            if (
                class_name
                == "COUPON_PROMO"
            ):
                promo_unlinked += 1

            else:
                result_unlinked += 1

            continue

        link_type = (
            "PROMO"
            if class_name
            == "COUPON_PROMO"

            else "CLAIMED_RESULT"
        )

        conn.execute(
            """
            INSERT OR IGNORE
            INTO karaca_coupon_links (
                coupon_id,
                linked_message_id,
                link_type,
                confidence,
                hours_after_primary
            )

            VALUES (?, ?, ?, ?, ?)
            """,
            (
                best[
                    "coupon_id"
                ],

                message_id,
                link_type,

                best[
                    "confidence"
                ],

                round(
                    best[
                        "hours"
                    ],
                    3,
                ),
            ),
        )

        if (
            class_name
            == "COUPON_PROMO"
        ):
            promo_linked += 1

        else:
            result_linked += 1

            conn.execute(
                """
                UPDATE karaca_coupons

                SET
                    claimed_result =
                        'CLAIMED_WIN',

                    claimed_result_message_id =
                        ?,

                    claimed_result_received_at =
                        ?,

                    result_link_confidence =
                        ?

                WHERE id = ?
                """,
                (
                    message_id,
                    received_at,

                    best[
                        "confidence"
                    ],

                    best[
                        "coupon_id"
                    ],
                ),
            )

    conn.commit()

    return (
        promo_linked,
        promo_unlinked,
        result_linked,
        result_unlinked,
    )


def export_audit_csv(conn):
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        REPORT_DIR
        / "karaca_coupon_audit.csv"
    )

    rows = conn.execute(
        """
        SELECT
            c.id,
            c.primary_message_id,
            c.telegram_received_at,
            c.coupon_date,
            c.start_time,
            c.advertised_odds,
            c.match_count,

            c.claimed_result,
            c.claimed_result_message_id,
            c.claimed_result_received_at,
            c.result_link_confidence,

            c.verification_status

        FROM karaca_coupons c

        ORDER BY
            c.telegram_received_at
        """
    ).fetchall()

    headers = [
        "coupon_id",
        "primary_message_id",
        "telegram_received_at",
        "coupon_date",
        "start_time",
        "advertised_odds",
        "match_count",

        "claimed_result",
        "claimed_result_message_id",
        "claimed_result_received_at",
        "result_link_confidence",

        "verification_status",
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.writer(
            f
        )

        writer.writerow(
            headers
        )

        writer.writerows(
            rows
        )

    return path


def print_summary(conn):
    coupon_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons
        """
    ).fetchone()[0]

    match_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupon_matches
        """
    ).fetchone()[0]

    claimed_wins = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons
        WHERE claimed_result =
              'CLAIMED_WIN'
        """
    ).fetchone()[0]

    high_conf = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons
        WHERE result_link_confidence =
              'HIGH'
        """
    ).fetchone()[0]

    medium_conf = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons
        WHERE result_link_confidence =
              'MEDIUM'
        """
    ).fetchone()[0]

    low_conf = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons
        WHERE result_link_confidence =
              'LOW'
        """
    ).fetchone()[0]

    zero_match = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons
        WHERE match_count = 0
        """
    ).fetchone()[0]

    date_range = conn.execute(
        """
        SELECT
            MIN(coupon_date),
            MAX(coupon_date)

        FROM karaca_coupons
        """
    ).fetchone()

    odds_rows = conn.execute(
        """
        SELECT
            advertised_odds,
            COUNT(*)

        FROM karaca_coupons

        WHERE advertised_odds
              IS NOT NULL

        GROUP BY advertised_odds

        ORDER BY COUNT(*) DESC
        LIMIT 10
        """
    ).fetchall()

    print()
    print(
        "JARVIS KARACA COUPON PARSER"
    )
    print("=" * 70)

    print(
        "Primary coupons:",
        coupon_count,
    )

    print(
        "Parsed match rows:",
        match_count,
    )

    print(
        "Coupons with zero parsed matches:",
        zero_match,
    )

    print(
        "Claimed wins linked:",
        claimed_wins,
    )

    print()

    print(
        "Result link confidence:"
    )

    print(
        "  HIGH:",
        high_conf,
    )

    print(
        "  MEDIUM:",
        medium_conf,
    )

    print(
        "  LOW:",
        low_conf,
    )

    print()

    print(
        "Coupon date range:",
        date_range[0],
        "->",
        date_range[1],
    )

    print()
    print(
        "Most common advertised odds:"
    )

    for odds, count in odds_rows:
        print(
            f"  {odds}: {count}"
        )


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"Database not found: "
            f"{DB_PATH}"
        )

    conn = sqlite3.connect(
        DB_PATH
    )

    ensure_tables(
        conn
    )

    clear_generated_data(
        conn
    )

    messages = (
        load_karaca_messages(
            conn
        )
    )

    (
        primary_count,
        parsed_match_count,
        empty_coupon_count,
    ) = insert_primary_coupons(
        conn,
        messages,
    )

    (
        promo_linked,
        promo_unlinked,
        result_linked,
        result_unlinked,
    ) = link_promos_and_results(
        conn,
        messages,
    )

    report_path = (
        export_audit_csv(
            conn
        )
    )

    print_summary(
        conn
    )

    print()
    print(
        "LINKING REPORT"
    )
    print("=" * 70)

    print(
        "Promo linked:",
        promo_linked,
    )

    print(
        "Promo unlinked:",
        promo_unlinked,
    )

    print(
        "Result linked:",
        result_linked,
    )

    print(
        "Result unlinked:",
        result_unlinked,
    )

    print()
    print(
        "Audit report:",
        report_path,
    )

    print()
    print(
        "IMPORTANT:"
    )

    print(
        "CLAIMED_WIN means only that "
        "the Telegram channel claimed "
        "the coupon won."
    )

    print(
        "It is NOT yet independently "
        "verified against football results."
    )

    conn.close()


if __name__ == "__main__":
    main()