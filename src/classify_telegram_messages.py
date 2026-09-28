import sqlite3
import unicodedata
from pathlib import Path


DB_PATH = Path("data/forward/jarvis_forward.db")


GENERIC_COUPON_WORDS = [
    "kupon",
    "gunun maclari",
    "gunun kuponu",
    "banko",
    "kombine",
    "ms&toplam gol",
    "ms toplam gol",
    "oran",
]

GENERIC_RESULT_WORDS = [
    "basariyla sonuclandi",
    "kazandi",
    "kazandik",
    "tuttu",
    "tebrikler",
    "win",
]

GENERIC_RECEIPT_WORDS = [
    "dekont",
    "odeme",
    "havale",
    "eft",
    "iban",
    "banka",
]

GENERIC_AD_WORDS = [
    "uyelik",
    "abonelik",
    "ozel grup",
    "katilim",
    "kampanya",
    "iletisim",
    "alimlar basladi",
]

GENERIC_TESTIMONIAL_WORDS = [
    "tesekkur",
    "sayende",
    "kazandirdin",
]


def normalize(value):
    if not value:
        return ""

    value = str(value).lower()

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


def contains(text, phrase):
    return normalize(phrase) in text


def score_words(text, words):
    return sum(
        1
        for word in words
        if normalize(word) in text
    )


def classify_karaca(text, media_type):
    """
    Deterministic rules learned from KARACA channel format.
    """

    # Winning coupon result
    if (
        "gunun kuponu basariyla sonuclandi"
        in text
    ):
        return (
            "COUPON_RESULT",
            100,
            "karaca_exact_result",
        )

    # Main daily coupon post
    if (
        "gunun maclari" in text
        and "baslama saatleri" in text
    ):
        return (
            "COUPON_PRIMARY",
            100,
            "karaca_exact_primary",
        )

    # Promotional repost of the same coupon
    if (
        "kupon yapmayi dusunenler"
        in text
        and "firsati kacirmayin"
        in text
    ):
        return (
            "COUPON_PROMO",
            100,
            "karaca_exact_promo",
        )

    # Bank receipt / participant payout sharing
    if (
        "kazanclarini paylasan tum katilimcilarimizi"
        in text
    ):
        return (
            "BANK_RECEIPT",
            100,
            "karaca_exact_receipt",
        )

    if (
        "duzenli analizler" in text
        and "istikrarli sonuclar" in text
        and "bizi tercih eden" in text
    ):
        return (
            "BANK_RECEIPT",
            95,
            "karaca_receipt_pattern",
        )

    if media_type == "photo":
        return (
            "UNKNOWN_IMAGE",
            0,
            "karaca_unknown_image",
        )

    return (
        "OTHER",
        0,
        "karaca_other",
    )


def classify_generic(text, media_type):
    coupon_score = score_words(
        text,
        GENERIC_COUPON_WORDS,
    )

    result_score = score_words(
        text,
        GENERIC_RESULT_WORDS,
    )

    receipt_score = score_words(
        text,
        GENERIC_RECEIPT_WORDS,
    )

    ad_score = score_words(
        text,
        GENERIC_AD_WORDS,
    )

    testimonial_score = score_words(
        text,
        GENERIC_TESTIMONIAL_WORDS,
    )

    if (
        result_score >= 1
        and coupon_score >= 1
    ):
        return (
            "COUPON_RESULT",
            result_score + coupon_score,
            "generic_result_coupon",
        )

    if receipt_score >= 2:
        return (
            "BANK_RECEIPT",
            receipt_score,
            "generic_receipt",
        )

    if testimonial_score >= 2:
        return (
            "TESTIMONIAL",
            testimonial_score,
            "generic_testimonial",
        )

    if ad_score >= 3:
        return (
            "ADVERTISEMENT",
            ad_score,
            "generic_ad",
        )

    if coupon_score >= 3:
        return (
            "COUPON",
            coupon_score,
            "generic_coupon",
        )

    if result_score >= 2:
        return (
            "COUPON_RESULT",
            result_score,
            "generic_result",
        )

    if media_type == "photo":
        return (
            "UNKNOWN_IMAGE",
            0,
            "generic_unknown_image",
        )

    return (
        "OTHER",
        0,
        "generic_other",
    )


def classify(
    source_chat_title,
    text,
    media_type,
):
    normalized_title = normalize(
        source_chat_title
    )

    normalized_text = normalize(
        text
    )

    if "karaca" in normalized_title:
        return classify_karaca(
            normalized_text,
            media_type,
        )

    return classify_generic(
        normalized_text,
        media_type,
    )


def ensure_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_classification (
            source_chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            predicted_class TEXT NOT NULL,
            rule_score INTEGER DEFAULT 0,
            classification_method TEXT,
            reviewed INTEGER DEFAULT 0,
            final_class TEXT,

            PRIMARY KEY (
                source_chat_id,
                message_id
            )
        )
        """
    )

    columns = {
        row[1]
        for row in conn.execute(
            """
            PRAGMA table_info(
                telegram_classification
            )
            """
        ).fetchall()
    }

    if (
        "classification_method"
        not in columns
    ):
        conn.execute(
            """
            ALTER TABLE telegram_classification
            ADD COLUMN classification_method TEXT
            """
        )

    conn.commit()


def classify_all(conn):
    messages = conn.execute(
        """
        SELECT
            source_chat_id,
            source_chat_title,
            message_id,
            text,
            media_type

        FROM telegram_messages
        """
    ).fetchall()

    for (
        chat_id,
        chat_title,
        message_id,
        text,
        media_type,
    ) in messages:

        (
            predicted_class,
            score,
            method,
        ) = classify(
            chat_title or "",
            text or "",
            media_type,
        )

        conn.execute(
            """
            INSERT INTO telegram_classification (
                source_chat_id,
                message_id,
                predicted_class,
                rule_score,
                classification_method
            )

            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT (
                source_chat_id,
                message_id
            )

            DO UPDATE SET
                predicted_class =
                    excluded.predicted_class,

                rule_score =
                    excluded.rule_score,

                classification_method =
                    excluded.classification_method
            """,
            (
                chat_id,
                message_id,
                predicted_class,
                score,
                method,
            ),
        )

    conn.commit()


def print_summary(conn):
    print()
    print(
        "JARVIS TELEGRAM CLASSIFICATION V2"
    )
    print("=" * 70)

    rows = conn.execute(
        """
        SELECT
            predicted_class,
            COUNT(*)

        FROM telegram_classification

        GROUP BY predicted_class

        ORDER BY COUNT(*) DESC
        """
    ).fetchall()

    total = 0

    for label, count in rows:
        total += count

        print(
            f"{label:22s}: {count}"
        )

    print("-" * 70)

    print(
        f"{'TOTAL':22s}: {total}"
    )

    print()
    print("CHANNEL BREAKDOWN")
    print("=" * 70)

    rows = conn.execute(
        """
        SELECT
            m.source_chat_title,
            c.predicted_class,
            COUNT(*)

        FROM telegram_classification c

        JOIN telegram_messages m
          ON m.source_chat_id =
             c.source_chat_id

         AND m.message_id =
             c.message_id

        GROUP BY
            m.source_chat_title,
            c.predicted_class

        ORDER BY
            m.source_chat_title,
            COUNT(*) DESC
        """
    ).fetchall()

    current_channel = None

    for (
        channel,
        label,
        count,
    ) in rows:

        if channel != current_channel:
            print()
            print(channel)

            current_channel = channel

        print(
            f"  {label:22s}: {count}"
        )

    print()
    print("KARACA EXACT PATTERN SUMMARY")
    print("=" * 70)

    rows = conn.execute(
        """
        SELECT
            classification_method,
            COUNT(*)

        FROM telegram_classification c

        JOIN telegram_messages m
          ON m.source_chat_id =
             c.source_chat_id

         AND m.message_id =
             c.message_id

        WHERE lower(
            m.source_chat_title
        ) LIKE '%karaca%'

        GROUP BY classification_method

        ORDER BY COUNT(*) DESC
        """
    ).fetchall()

    for method, count in rows:
        print(
            f"{method:30s}: {count}"
        )


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"Database not found: {DB_PATH}"
        )

    conn = sqlite3.connect(
        DB_PATH
    )

    ensure_table(
        conn
    )

    classify_all(
        conn
    )

    print_summary(
        conn
    )

    conn.close()


if __name__ == "__main__":
    main()