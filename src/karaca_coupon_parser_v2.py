import csv
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo


DB_PATH = Path("data/forward/jarvis_forward.db")
REPORT_DIR = Path("reports")

ISTANBUL = ZoneInfo("Europe/Istanbul")

RESULT_NEXT_DAY_CUTOFF = time(5, 0)


# ============================================================
# TEXT / DATE HELPERS
# ============================================================

def normalize_text(value):
    if not value:
        return ""

    value = str(value)

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

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = value.lower()

    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        ch
        for ch in value
        if not unicodedata.combining(ch)
    )

    return value


def parse_iso(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

    except ValueError:
        return None


def to_istanbul(value):
    dt = parse_iso(value)

    if dt is None:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=ISTANBUL
        )

    return dt.astimezone(
        ISTANBUL
    )


def extract_declared_date(text):
    if not text:
        return None

    match = re.search(
        r"[\{\[\(]?\s*"
        r"(\d{1,2})\."
        r"(\d{1,2})\."
        r"(\d{4})"
        r"\s*[\}\]\)]?",
        text,
    )

    if not match:
        return None

    try:
        return datetime(
            int(match.group(3)),
            int(match.group(2)),
            int(match.group(1)),
            tzinfo=ISTANBUL,
        ).date()

    except ValueError:
        return None


def extract_start_times(text):
    """
    Examples:

    Başlama Saatleri: 19:00
    Başlama Saatleri: 19:00 - 20:30
    """

    normalized = normalize_text(
        text
    )

    relevant_line = None

    for line in normalized.splitlines():
        if "baslama saat" in line:
            relevant_line = line
            break

    if not relevant_line:
        return (
            None,
            None,
            None,
        )

    times = re.findall(
        r"\b([0-2]?\d:[0-5]\d)\b",
        relevant_line,
    )

    if not times:
        return (
            None,
            None,
            relevant_line.strip(),
        )

    first_time = times[0]

    last_time = (
        times[-1]
        if len(times) > 1
        else times[0]
    )

    return (
        first_time,
        last_time,
        relevant_line.strip(),
    )


def extract_advertised_odds(text):
    if not text:
        return None

    normalized = normalize_text(
        text
    )

    match = re.search(
        r"\+\s*(\d{2,4})\s*oran",
        normalized,
    )

    if match:
        return (
            "+"
            + match.group(1)
        )

    match = re.search(
        r"\b(\d+[.,]\d+)\s*oran",
        normalized,
    )

    if match:
        return (
            match.group(1)
            .replace(",", ".")
        )

    return None


# ============================================================
# MATCH PARSER
# ============================================================

PREFIX_CHARS = (
    "➡️",
    "➡",
    "➜",
    "➤",
    "▶️",
    "▶",
    "►",
    "•",
    "🔣",
    "⚽",
    "▪️",
    "▪",
    "▫️",
    "▫",
)


DASH_TRANSLATION = str.maketrans(
    {
        "–": "-",
        "—": "-",
        "−": "-",
        "-": "-",
        "‒": "-",
    }
)


def strip_match_prefix(line):
    value = line.strip()

    changed = True

    while changed:
        changed = False

        for prefix in PREFIX_CHARS:
            if value.startswith(prefix):
                value = value[
                    len(prefix):
                ].strip()

                changed = True

    return value


def normalize_match_dash(line):
    value = line.translate(
        DASH_TRANSLATION
    )

    value = re.sub(
        r"\s+-\s+",
        " - ",
        value,
    )

    return value


def looks_like_match_line(line):
    if not line:
        return False

    normalized = normalize_text(
        line
    )

    blocked_phrases = (
        "gunun maclari",
        "baslama saat",
        "iletisim",
        "oran",
        "kupon",
        "analiz",
        "firsat",
        "sonuclandi",
        "bugun",
    )

    for phrase in blocked_phrases:
        if phrase in normalized:
            return False

    normalized_dash = (
        normalize_match_dash(
            line
        )
    )

    if " - " not in normalized_dash:
        return False

    parts = normalized_dash.split(
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

    if not text:
        return matches

    for raw_line in text.splitlines():
        line = strip_match_prefix(
            raw_line
        )

        line = normalize_match_dash(
            line
        )

        if not looks_like_match_line(
            line
        ):
            continue

        home, away = line.split(
            " - ",
            1,
        )

        home = home.strip()
        away = away.strip()

        if not home or not away:
            continue

        matches.append(
            {
                "home_team": home,
                "away_team": away,
                "raw_line": raw_line.strip(),
            }
        )

    return matches


# ============================================================
# DATABASE
# ============================================================

def rebuild_v2_tables(conn):
    """
    Only V2 generated tables are rebuilt.

    Raw Telegram tables and V1 tables
    remain untouched.
    """

    tables = [
        "karaca_result_candidates_v2",
        "karaca_promos_v2",
        "karaca_results_v2",
        "karaca_coupon_matches_v2",
        "karaca_coupons_v2",
    ]

    for table in tables:
        conn.execute(
            f"DROP TABLE IF EXISTS {table}"
        )

    conn.execute(
        """
        CREATE TABLE karaca_coupons_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            source_chat_id INTEGER NOT NULL,
            primary_message_id INTEGER NOT NULL UNIQUE,

            telegram_received_at TEXT NOT NULL,

            telegram_local_datetime TEXT,
            telegram_local_date TEXT,

            declared_coupon_date TEXT,
            effective_coupon_date TEXT,

            date_mismatch INTEGER DEFAULT 0,

            start_time_first TEXT,
            start_time_last TEXT,
            start_time_raw TEXT,

            advertised_odds TEXT,

            raw_caption TEXT,

            match_count INTEGER DEFAULT 0,

            coupon_status TEXT
                DEFAULT 'PRIMARY_ONLY',

            linked_result_count INTEGER DEFAULT 0,

            ambiguous_result_candidate_count
                INTEGER DEFAULT 0,

            parser_version TEXT
                DEFAULT 'KARACA_V2',

            created_at TEXT
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE karaca_coupon_matches_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            coupon_id INTEGER NOT NULL,

            selection_order INTEGER NOT NULL,

            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,

            raw_line TEXT,

            visible_market TEXT,
            visible_selection TEXT,

            hidden_prediction TEXT,
            hidden_confidence REAL,

            actual_hidden_selection TEXT,

            actual_match_result TEXT,
            actual_score TEXT,

            prediction_correct INTEGER,

            FOREIGN KEY (
                coupon_id
            )
            REFERENCES karaca_coupons_v2(id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE karaca_results_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            source_chat_id INTEGER NOT NULL,

            result_message_id INTEGER
                NOT NULL UNIQUE,

            telegram_received_at TEXT NOT NULL,

            telegram_local_datetime TEXT,
            telegram_local_date TEXT,
            telegram_local_time TEXT,

            raw_caption TEXT,

            media_path TEXT,

            link_status TEXT NOT NULL,

            linked_coupon_id INTEGER,

            candidate_count INTEGER DEFAULT 0,

            link_rule TEXT,

            hours_after_primary REAL,

            claim_type TEXT
                DEFAULT 'CLAIMED_WIN',

            independent_verification TEXT
                DEFAULT 'UNVERIFIED',

            FOREIGN KEY (
                linked_coupon_id
            )
            REFERENCES karaca_coupons_v2(id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE karaca_result_candidates_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            result_message_id INTEGER NOT NULL,

            coupon_id INTEGER NOT NULL,

            candidate_rule TEXT,

            hours_after_primary REAL,

            UNIQUE(
                result_message_id,
                coupon_id
            ),

            FOREIGN KEY (
                coupon_id
            )
            REFERENCES karaca_coupons_v2(id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE karaca_promos_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            source_chat_id INTEGER NOT NULL,

            promo_message_id INTEGER
                NOT NULL UNIQUE,

            telegram_received_at TEXT,

            telegram_local_datetime TEXT,

            linked_coupon_id INTEGER,

            hours_after_primary REAL,

            link_status TEXT,

            FOREIGN KEY (
                linked_coupon_id
            )
            REFERENCES karaca_coupons_v2(id)
        )
        """
    )

    conn.commit()


# ============================================================
# SOURCE DATA
# ============================================================

def load_karaca_messages(conn):
    rows = conn.execute(
        """
        SELECT
            m.source_chat_id,
            m.source_chat_title,
            m.message_id,
            m.received_at,

            COALESCE(
                m.text,
                ''
            ),

            m.media_path,

            COALESCE(
                NULLIF(
                    c.final_class,
                    ''
                ),
                c.predicted_class,
                'UNKNOWN'
            ) AS class_name

        FROM telegram_messages m

        LEFT JOIN telegram_classification c
          ON c.source_chat_id =
             m.source_chat_id

         AND c.message_id =
             m.message_id

        ORDER BY
            m.received_at
        """
    ).fetchall()

    result = []

    for row in rows:
        title = normalize_text(
            row[1]
        )

        if "karaca" in title:
            result.append(row)

    return result


# ============================================================
# PRIMARY COUPONS
# ============================================================

def insert_primary_coupons(
    conn,
    messages,
):
    primary_count = 0
    match_count = 0

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

        if class_name != "COUPON_PRIMARY":
            continue

        local_dt = to_istanbul(
            received_at
        )

        local_date = (
            local_dt.date()
            if local_dt
            else None
        )

        declared_date = (
            extract_declared_date(
                text
            )
        )

        date_mismatch = 0

        if (
            declared_date is not None
            and local_date is not None
            and declared_date != local_date
        ):
            date_mismatch = 1

        if (
            declared_date is not None
            and date_mismatch == 0
        ):
            effective_date = (
                declared_date
            )

        else:
            effective_date = (
                local_date
                or declared_date
            )

        (
            start_first,
            start_last,
            start_raw,
        ) = extract_start_times(
            text
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
            INSERT INTO karaca_coupons_v2 (
                source_chat_id,
                primary_message_id,

                telegram_received_at,
                telegram_local_datetime,
                telegram_local_date,

                declared_coupon_date,
                effective_coupon_date,

                date_mismatch,

                start_time_first,
                start_time_last,
                start_time_raw,

                advertised_odds,

                raw_caption,

                match_count
            )

            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
            """,
            (
                chat_id,
                message_id,

                received_at,

                (
                    local_dt.isoformat()
                    if local_dt
                    else None
                ),

                (
                    str(local_date)
                    if local_date
                    else None
                ),

                (
                    str(declared_date)
                    if declared_date
                    else None
                ),

                (
                    str(effective_date)
                    if effective_date
                    else None
                ),

                date_mismatch,

                start_first,
                start_last,
                start_raw,

                advertised_odds,

                text,

                len(matches),
            ),
        )

        coupon_id = cursor.lastrowid

        for index, match in enumerate(
            matches,
            start=1,
        ):
            conn.execute(
                """
                INSERT INTO
                karaca_coupon_matches_v2 (
                    coupon_id,
                    selection_order,
                    home_team,
                    away_team,
                    raw_line
                )

                VALUES (?, ?, ?, ?, ?)
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

                    match[
                        "raw_line"
                    ],
                ),
            )

            match_count += 1

        primary_count += 1

    conn.commit()

    return (
        primary_count,
        match_count,
    )


# ============================================================
# RESULT LINKING
# ============================================================

def load_coupons_for_chat(
    conn,
    chat_id,
):
    return conn.execute(
        """
        SELECT
            id,
            primary_message_id,
            telegram_received_at,
            telegram_local_datetime,
            telegram_local_date,
            effective_coupon_date

        FROM karaca_coupons_v2

        WHERE source_chat_id = ?

        ORDER BY
            telegram_received_at
        """,
        (
            chat_id,
        ),
    ).fetchall()


def valid_result_candidate(
    primary_local_dt,
    result_local_dt,
):
    if (
        primary_local_dt is None
        or result_local_dt is None
    ):
        return (
            False,
            None,
        )

    if result_local_dt <= primary_local_dt:
        return (
            False,
            None,
        )

    primary_date = (
        primary_local_dt.date()
    )

    result_date = (
        result_local_dt.date()
    )

    if result_date == primary_date:
        return (
            True,
            "SAME_LOCAL_DATE",
        )

    next_day = (
        primary_date
        + timedelta(days=1)
    )

    if (
        result_date == next_day
        and result_local_dt.time()
        <= RESULT_NEXT_DAY_CUTOFF
    ):
        return (
            True,
            "NEXT_DAY_BEFORE_05",
        )

    return (
        False,
        None,
    )


def get_result_candidates(
    coupons,
    result_local_dt,
):
    candidates = []

    for coupon in coupons:
        (
            coupon_id,
            primary_message_id,
            telegram_received_at,
            primary_local_iso,
            primary_local_date,
            effective_date,
        ) = coupon

        primary_local_dt = (
            parse_iso(
                primary_local_iso
            )
        )

        (
            valid,
            rule,
        ) = valid_result_candidate(
            primary_local_dt,
            result_local_dt,
        )

        if not valid:
            continue

        hours_after = (
            (
                result_local_dt
                - primary_local_dt
            )
            .total_seconds()
            / 3600
        )

        candidates.append(
            {
                "coupon_id":
                    coupon_id,

                "primary_message_id":
                    primary_message_id,

                "rule":
                    rule,

                "hours_after":
                    round(
                        hours_after,
                        3,
                    ),
            }
        )

    return candidates


def insert_results(
    conn,
    messages,
):
    chat_ids = sorted(
        {
            row[0]
            for row in messages
        }
    )

    coupon_cache = {
        chat_id:
            load_coupons_for_chat(
                conn,
                chat_id,
            )

        for chat_id in chat_ids
    }

    linked = 0
    result_only = 0
    ambiguous = 0

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

        if class_name != "COUPON_RESULT":
            continue

        local_dt = to_istanbul(
            received_at
        )

        candidates = (
            get_result_candidates(
                coupon_cache.get(
                    chat_id,
                    [],
                ),
                local_dt,
            )
        )

        linked_coupon_id = None
        link_status = None
        link_rule = None
        hours_after = None

        if len(candidates) == 1:
            candidate = (
                candidates[0]
            )

            linked_coupon_id = (
                candidate[
                    "coupon_id"
                ]
            )

            link_status = "LINKED"

            link_rule = (
                candidate[
                    "rule"
                ]
            )

            hours_after = (
                candidate[
                    "hours_after"
                ]
            )

            linked += 1

        elif len(candidates) == 0:
            link_status = (
                "RESULT_ONLY"
            )

            result_only += 1

        else:
            link_status = (
                "AMBIGUOUS"
            )

            ambiguous += 1

        conn.execute(
            """
            INSERT INTO karaca_results_v2 (
                source_chat_id,
                result_message_id,

                telegram_received_at,
                telegram_local_datetime,
                telegram_local_date,
                telegram_local_time,

                raw_caption,
                media_path,

                link_status,
                linked_coupon_id,

                candidate_count,

                link_rule,
                hours_after_primary
            )

            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                chat_id,
                message_id,

                received_at,

                (
                    local_dt.isoformat()
                    if local_dt
                    else None
                ),

                (
                    str(
                        local_dt.date()
                    )
                    if local_dt
                    else None
                ),

                (
                    local_dt
                    .time()
                    .isoformat(
                        timespec="seconds"
                    )
                    if local_dt
                    else None
                ),

                text,
                media_path,

                link_status,
                linked_coupon_id,

                len(candidates),

                link_rule,
                hours_after,
            ),
        )

        for candidate in candidates:
            conn.execute(
                """
                INSERT OR IGNORE INTO
                karaca_result_candidates_v2 (
                    result_message_id,
                    coupon_id,
                    candidate_rule,
                    hours_after_primary
                )

                VALUES (?, ?, ?, ?)
                """,
                (
                    message_id,

                    candidate[
                        "coupon_id"
                    ],

                    candidate[
                        "rule"
                    ],

                    candidate[
                        "hours_after"
                    ],
                ),
            )

    conn.commit()

    return (
        linked,
        result_only,
        ambiguous,
    )


# ============================================================
# PROMO LINKING
# ============================================================

def insert_promos(
    conn,
    messages,
):
    chat_ids = sorted(
        {
            row[0]
            for row in messages
        }
    )

    coupon_cache = {
        chat_id:
            load_coupons_for_chat(
                conn,
                chat_id,
            )

        for chat_id in chat_ids
    }

    linked_count = 0
    unlinked_count = 0

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

        if class_name != "COUPON_PROMO":
            continue

        promo_local_dt = (
            to_istanbul(
                received_at
            )
        )

        candidates = []

        for coupon in coupon_cache.get(
            chat_id,
            [],
        ):
            (
                coupon_id,
                primary_message_id,
                primary_received_at,
                primary_local_iso,
                primary_local_date,
                effective_date,
            ) = coupon

            primary_local_dt = (
                parse_iso(
                    primary_local_iso
                )
            )

            if (
                primary_local_dt is None
                or promo_local_dt is None
            ):
                continue

            if promo_local_dt <= primary_local_dt:
                continue

            if (
                promo_local_dt.date()
                != primary_local_dt.date()
            ):
                continue

            hours_after = (
                (
                    promo_local_dt
                    - primary_local_dt
                )
                .total_seconds()
                / 3600
            )

            candidates.append(
                (
                    coupon_id,
                    hours_after,
                )
            )

        if candidates:
            candidates.sort(
                key=lambda x: x[1]
            )

            coupon_id, hours_after = (
                candidates[0]
            )

            status = "LINKED"

            linked_count += 1

        else:
            coupon_id = None
            hours_after = None
            status = "UNLINKED"

            unlinked_count += 1

        conn.execute(
            """
            INSERT INTO karaca_promos_v2 (
                source_chat_id,
                promo_message_id,

                telegram_received_at,
                telegram_local_datetime,

                linked_coupon_id,
                hours_after_primary,

                link_status
            )

            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                message_id,
                received_at,

                (
                    promo_local_dt
                    .isoformat()
                    if promo_local_dt
                    else None
                ),

                coupon_id,
                (
                    round(
                        hours_after,
                        3,
                    )
                    if hours_after
                    is not None
                    else None
                ),

                status,
            ),
        )

    conn.commit()

    return (
        linked_count,
        unlinked_count,
    )


# ============================================================
# COUPON STATUS
# ============================================================

def update_coupon_statuses(conn):
    coupons = conn.execute(
        """
        SELECT id
        FROM karaca_coupons_v2
        """
    ).fetchall()

    for (
        coupon_id,
    ) in coupons:

        linked_count = (
            conn.execute(
                """
                SELECT COUNT(*)

                FROM karaca_results_v2

                WHERE linked_coupon_id = ?

                  AND link_status =
                      'LINKED'
                """,
                (
                    coupon_id,
                ),
            ).fetchone()[0]
        )

        ambiguous_candidate_count = (
            conn.execute(
                """
                SELECT COUNT(*)

                FROM karaca_result_candidates_v2 rc

                JOIN karaca_results_v2 r
                  ON r.result_message_id =
                     rc.result_message_id

                WHERE rc.coupon_id = ?

                  AND r.link_status =
                      'AMBIGUOUS'
                """,
                (
                    coupon_id,
                ),
            ).fetchone()[0]
        )

        if linked_count == 0:
            if (
                ambiguous_candidate_count
                > 0
            ):
                status = (
                    "PRIMARY_AMBIGUOUS"
                )

            else:
                status = (
                    "PRIMARY_ONLY"
                )

        elif linked_count == 1:
            status = (
                "PRIMARY_WITH_RESULT"
            )

        else:
            status = (
                "PRIMARY_WITH_MULTIPLE_RESULTS"
            )

        conn.execute(
            """
            UPDATE karaca_coupons_v2

            SET
                coupon_status = ?,

                linked_result_count = ?,

                ambiguous_result_candidate_count
                    = ?

            WHERE id = ?
            """,
            (
                status,
                linked_count,
                ambiguous_candidate_count,
                coupon_id,
            ),
        )

    conn.commit()


# ============================================================
# EXPORTS
# ============================================================

def export_coupon_csv(conn):
    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        REPORT_DIR
        / "karaca_v2_coupon_audit.csv"
    )

    rows = conn.execute(
        """
        SELECT
            id,
            primary_message_id,

            telegram_received_at,
            telegram_local_datetime,
            telegram_local_date,

            declared_coupon_date,
            effective_coupon_date,

            date_mismatch,

            start_time_first,
            start_time_last,

            advertised_odds,

            match_count,

            coupon_status,

            linked_result_count,

            ambiguous_result_candidate_count

        FROM karaca_coupons_v2

        ORDER BY
            telegram_received_at
        """
    ).fetchall()

    headers = [
        "coupon_id",
        "primary_message_id",

        "telegram_received_at",
        "telegram_local_datetime",
        "telegram_local_date",

        "declared_coupon_date",
        "effective_coupon_date",

        "date_mismatch",

        "start_time_first",
        "start_time_last",

        "advertised_odds",

        "match_count",

        "coupon_status",

        "linked_result_count",

        "ambiguous_result_candidate_count",
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        writer = csv.writer(f)

        writer.writerow(
            headers
        )

        writer.writerows(
            rows
        )

    return path


def export_match_csv(conn):
    path = (
        REPORT_DIR
        / "karaca_v2_matches.csv"
    )

    rows = conn.execute(
        """
        SELECT
            c.id,
            c.primary_message_id,
            c.effective_coupon_date,

            m.selection_order,
            m.home_team,
            m.away_team,
            m.raw_line

        FROM karaca_coupon_matches_v2 m

        JOIN karaca_coupons_v2 c
          ON c.id =
             m.coupon_id

        ORDER BY
            c.telegram_received_at,
            m.selection_order
        """
    ).fetchall()

    headers = [
        "coupon_id",
        "primary_message_id",
        "effective_coupon_date",

        "selection_order",
        "home_team",
        "away_team",
        "raw_line",
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        writer = csv.writer(f)

        writer.writerow(
            headers
        )

        writer.writerows(
            rows
        )

    return path


def export_result_csv(conn):
    path = (
        REPORT_DIR
        / "karaca_v2_result_audit.csv"
    )

    rows = conn.execute(
        """
        SELECT
            result_message_id,

            telegram_received_at,
            telegram_local_datetime,
            telegram_local_date,
            telegram_local_time,

            link_status,
            linked_coupon_id,

            candidate_count,
            link_rule,
            hours_after_primary,

            claim_type,
            independent_verification

        FROM karaca_results_v2

        ORDER BY
            telegram_received_at
        """
    ).fetchall()

    headers = [
        "result_message_id",

        "telegram_received_at",
        "telegram_local_datetime",
        "telegram_local_date",
        "telegram_local_time",

        "link_status",
        "linked_coupon_id",

        "candidate_count",
        "link_rule",
        "hours_after_primary",

        "claim_type",
        "independent_verification",
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        writer = csv.writer(f)

        writer.writerow(
            headers
        )

        writer.writerows(
            rows
        )

    return path


def export_unparsed_csv(conn):
    path = (
        REPORT_DIR
        / "karaca_v2_unparsed_primary.csv"
    )

    rows = conn.execute(
        """
        SELECT
            id,
            primary_message_id,
            effective_coupon_date,
            advertised_odds,
            raw_caption

        FROM karaca_coupons_v2

        WHERE match_count != 4

        ORDER BY
            telegram_received_at
        """
    ).fetchall()

    headers = [
        "coupon_id",
        "primary_message_id",
        "effective_coupon_date",
        "advertised_odds",
        "raw_caption",
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        writer = csv.writer(f)

        writer.writerow(
            headers
        )

        writer.writerows(
            rows
        )

    return path


# ============================================================
# REPORT
# ============================================================

def print_summary(conn):
    primary_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons_v2
        """
    ).fetchone()[0]

    total_matches = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupon_matches_v2
        """
    ).fetchone()[0]

    four_match_coupons = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons_v2
        WHERE match_count = 4
        """
    ).fetchone()[0]

    zero_match = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons_v2
        WHERE match_count = 0
        """
    ).fetchone()[0]

    non_four = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons_v2
        WHERE match_count != 4
        """
    ).fetchone()[0]

    date_mismatch = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_coupons_v2
        WHERE date_mismatch = 1
        """
    ).fetchone()[0]

    linked_results = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_results_v2
        WHERE link_status = 'LINKED'
        """
    ).fetchone()[0]

    result_only = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_results_v2
        WHERE link_status = 'RESULT_ONLY'
        """
    ).fetchone()[0]

    ambiguous_results = conn.execute(
        """
        SELECT COUNT(*)
        FROM karaca_results_v2
        WHERE link_status = 'AMBIGUOUS'
        """
    ).fetchone()[0]

    status_rows = conn.execute(
        """
        SELECT
            coupon_status,
            COUNT(*)

        FROM karaca_coupons_v2

        GROUP BY
            coupon_status

        ORDER BY
            COUNT(*) DESC
        """
    ).fetchall()

    result_rule_rows = conn.execute(
        """
        SELECT
            link_rule,
            COUNT(*)

        FROM karaca_results_v2

        WHERE link_status = 'LINKED'

        GROUP BY
            link_rule
        """
    ).fetchall()

    print()
    print(
        "JARVIS KARACA PARSER V2"
    )

    print("=" * 72)

    print(
        "Primary coupons:",
        primary_count,
    )

    print(
        "Total parsed match rows:",
        total_matches,
    )

    print(
        "Coupons with exactly 4 matches:",
        four_match_coupons,
    )

    print(
        "Zero-match coupons:",
        zero_match,
    )

    print(
        "Coupons not equal to 4 matches:",
        non_four,
    )

    print(
        "Declared-date mismatches:",
        date_mismatch,
    )

    print()
    print(
        "RESULT LINKING"
    )

    print("-" * 72)

    print(
        "Linked:",
        linked_results,
    )

    print(
        "Result-only:",
        result_only,
    )

    print(
        "Ambiguous:",
        ambiguous_results,
    )

    print()
    print(
        "COUPON STATUS"
    )

    print("-" * 72)

    for status, count in status_rows:
        print(
            f"{status:32s}: {count}"
        )

    print()
    print(
        "LINK RULES"
    )

    print("-" * 72)

    for rule, count in result_rule_rows:
        print(
            f"{str(rule):32s}: {count}"
        )

    print()


# ============================================================
# MAIN
# ============================================================

def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"Database not found: "
            f"{DB_PATH}"
        )

    conn = sqlite3.connect(
        DB_PATH
    )

    rebuild_v2_tables(
        conn
    )

    messages = (
        load_karaca_messages(
            conn
        )
    )

    (
        primary_count,
        match_count,
    ) = insert_primary_coupons(
        conn,
        messages,
    )

    (
        linked_results,
        result_only,
        ambiguous_results,
    ) = insert_results(
        conn,
        messages,
    )

    (
        promo_linked,
        promo_unlinked,
    ) = insert_promos(
        conn,
        messages,
    )

    update_coupon_statuses(
        conn
    )

    coupon_csv = (
        export_coupon_csv(
            conn
        )
    )

    match_csv = (
        export_match_csv(
            conn
        )
    )

    result_csv = (
        export_result_csv(
            conn
        )
    )

    unparsed_csv = (
        export_unparsed_csv(
            conn
        )
    )

    print_summary(
        conn
    )

    print(
        "PROMO LINKING"
    )

    print("-" * 72)

    print(
        "Promo linked:",
        promo_linked,
    )

    print(
        "Promo unlinked:",
        promo_unlinked,
    )

    print()
    print(
        "REPORT FILES"
    )

    print("-" * 72)

    print(
        "Coupons:",
        coupon_csv,
    )

    print(
        "Matches:",
        match_csv,
    )

    print(
        "Results:",
        result_csv,
    )

    print(
        "Unparsed:",
        unparsed_csv,
    )

    print()
    print(
        "IMPORTANT:"
    )

    print(
        "LINKED only means a Telegram result "
        "message was safely associated with a "
        "primary coupon by timestamp rules."
    )

    print(
        "CLAIMED_WIN is still NOT independent "
        "football-result verification."
    )

    conn.close()


if __name__ == "__main__":
    main()