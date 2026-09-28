import html
import sqlite3
from pathlib import Path


DB_PATH = Path(
    "data/forward/jarvis_forward.db"
)

REPORT_DIR = Path("reports")

REPORT_PATH = (
    REPORT_DIR
    / "karaca_deep_audit.html"
)


def esc(value):
    return html.escape(
        str(value or "")
    )


def image_uri(path_value):
    if not path_value:
        return None

    path = Path(
        path_value
    )

    if not path.exists():
        return None

    return path.resolve().as_uri()


def get_zero_match_coupons(conn):
    return conn.execute(
        """
        SELECT
            c.id,
            c.primary_message_id,
            c.telegram_received_at,
            c.coupon_date,
            c.start_time,
            c.advertised_odds,
            c.raw_caption,
            m.media_path

        FROM karaca_coupons c

        LEFT JOIN telegram_messages m
          ON m.source_chat_id =
             c.source_chat_id

         AND m.message_id =
             c.primary_message_id

        WHERE c.match_count = 0

        ORDER BY
            c.telegram_received_at
        """
    ).fetchall()


def get_multiple_result_coupons(conn):
    return conn.execute(
        """
        SELECT
            c.id,
            c.primary_message_id,
            c.coupon_date,
            c.raw_caption,
            m.media_path,
            COUNT(l.id) AS result_count

        FROM karaca_coupons c

        JOIN karaca_coupon_links l
          ON l.coupon_id = c.id

         AND l.link_type =
             'CLAIMED_RESULT'

        LEFT JOIN telegram_messages m
          ON m.source_chat_id =
             c.source_chat_id

         AND m.message_id =
             c.primary_message_id

        GROUP BY
            c.id,
            c.primary_message_id,
            c.coupon_date,
            c.raw_caption,
            m.media_path

        HAVING COUNT(l.id) > 1

        ORDER BY
            result_count DESC,
            c.coupon_date
        """
    ).fetchall()


def get_result_links(
    conn,
    coupon_id,
):
    return conn.execute(
        """
        SELECT
            l.linked_message_id,
            l.confidence,
            l.hours_after_primary,

            m.received_at,
            m.text,
            m.media_path

        FROM karaca_coupon_links l

        LEFT JOIN telegram_messages m
          ON m.message_id =
             l.linked_message_id

        WHERE l.coupon_id = ?

          AND l.link_type =
              'CLAIMED_RESULT'

        ORDER BY
            l.hours_after_primary
        """,
        (
            coupon_id,
        ),
    ).fetchall()


def get_unlinked_results(conn):
    return conn.execute(
        """
        SELECT
            m.source_chat_id,
            m.message_id,
            m.received_at,
            m.text,
            m.media_path

        FROM telegram_messages m

        JOIN telegram_classification c
          ON c.source_chat_id =
             m.source_chat_id

         AND c.message_id =
             m.message_id

        WHERE lower(
            m.source_chat_title
        ) LIKE '%karaca%'

          AND COALESCE(
                c.final_class,
                c.predicted_class
              ) = 'COUPON_RESULT'

          AND NOT EXISTS (
              SELECT 1

              FROM karaca_coupon_links l

              WHERE l.linked_message_id =
                    m.message_id

                AND l.link_type =
                    'CLAIMED_RESULT'
          )

        ORDER BY
            m.received_at
        """
    ).fetchall()


def get_all_coupons(conn):
    return conn.execute(
        """
        SELECT
            c.id,
            c.primary_message_id,
            c.coupon_date,
            c.start_time,
            c.advertised_odds,
            c.match_count,

            c.claimed_result,
            c.claimed_result_message_id,
            c.result_link_confidence,
            c.verification_status

        FROM karaca_coupons c

        ORDER BY
            c.coupon_date,
            c.telegram_received_at
        """
    ).fetchall()


def get_coupon_matches(
    conn,
    coupon_id,
):
    return conn.execute(
        """
        SELECT
            selection_order,
            home_team,
            away_team

        FROM karaca_coupon_matches

        WHERE coupon_id = ?

        ORDER BY
            selection_order
        """,
        (
            coupon_id,
        ),
    ).fetchall()


def make_image(path_value):
    uri = image_uri(
        path_value
    )

    if not uri:
        return (
            "<div class='missing'>"
            "Görsel bulunamadı"
            "</div>"
        )

    return (
        f"<img src='{uri}'>"
    )


def build_zero_match_section(
    rows,
):
    cards = []

    for row in rows:
        (
            coupon_id,
            message_id,
            received_at,
            coupon_date,
            start_time,
            advertised_odds,
            caption,
            media_path,
        ) = row

        cards.append(
            f"""
            <section class="card">

                <h3>
                    Coupon #{coupon_id}
                    — message {message_id}
                </h3>

                <div class="meta">
                    coupon_date:
                    {esc(coupon_date)}
                    |
                    received:
                    {esc(received_at)}
                    |
                    start:
                    {esc(start_time)}
                    |
                    odds:
                    {esc(advertised_odds)}
                </div>

                <div class="two">

                    <div>
                        {make_image(media_path)}
                    </div>

                    <div>
                        <pre>{esc(caption)}</pre>
                    </div>

                </div>

            </section>
            """
        )

    return "".join(
        cards
    )


def build_multiple_result_section(
    conn,
    rows,
):
    cards = []

    for row in rows:
        (
            coupon_id,
            primary_message_id,
            coupon_date,
            caption,
            media_path,
            result_count,
        ) = row

        result_rows = (
            get_result_links(
                conn,
                coupon_id,
            )
        )

        result_blocks = []

        for result in result_rows:
            (
                result_message_id,
                confidence,
                hours_after,
                received_at,
                text,
                result_media_path,
            ) = result

            result_blocks.append(
                f"""
                <div class="result-block">

                    <h4>
                        Result msg:
                        {result_message_id}
                    </h4>

                    <p>
                        confidence:
                        <strong>
                        {esc(confidence)}
                        </strong>

                        |
                        after:
                        {esc(hours_after)}h

                        |
                        received:
                        {esc(received_at)}
                    </p>

                    {make_image(
                        result_media_path
                    )}

                    <pre>
{esc(text)}
                    </pre>

                </div>
                """
            )

        cards.append(
            f"""
            <section class="card">

                <h3>
                    Coupon #{coupon_id}
                    —
                    primary {primary_message_id}
                    —
                    {result_count} result links
                </h3>

                <p>
                    Date:
                    {esc(coupon_date)}
                </p>

                <div class="two">

                    <div>
                        <h4>PRIMARY</h4>

                        {make_image(
                            media_path
                        )}

                        <pre>
{esc(caption)}
                        </pre>
                    </div>

                    <div>
                        <h4>
                            LINKED RESULTS
                        </h4>

                        {''.join(
                            result_blocks
                        )}
                    </div>

                </div>

            </section>
            """
        )

    return "".join(
        cards
    )


def build_unlinked_section(
    rows,
):
    cards = []

    for row in rows:
        (
            chat_id,
            message_id,
            received_at,
            text,
            media_path,
        ) = row

        cards.append(
            f"""
            <section class="card">

                <h3>
                    Unlinked result
                    — message {message_id}
                </h3>

                <p>
                    {esc(received_at)}
                </p>

                <div class="two">

                    <div>
                        {make_image(
                            media_path
                        )}
                    </div>

                    <div>
                        <pre>
{esc(text)}
                        </pre>
                    </div>

                </div>

            </section>
            """
        )

    return "".join(
        cards
    )


def build_coupon_table(
    conn,
    rows,
):
    table_rows = []

    for row in rows:
        (
            coupon_id,
            primary_message_id,
            coupon_date,
            start_time,
            advertised_odds,
            match_count,
            claimed_result,
            result_message_id,
            confidence,
            verification_status,
        ) = row

        matches = (
            get_coupon_matches(
                conn,
                coupon_id,
            )
        )

        matches_text = "<br>".join(
            f"{order}. "
            f"{esc(home)} "
            f"— "
            f"{esc(away)}"

            for (
                order,
                home,
                away,
            ) in matches
        )

        table_rows.append(
            f"""
            <tr>
                <td>
                    {coupon_id}
                </td>

                <td>
                    {primary_message_id}
                </td>

                <td>
                    {esc(coupon_date)}
                </td>

                <td>
                    {esc(start_time)}
                </td>

                <td>
                    {esc(advertised_odds)}
                </td>

                <td>
                    {match_count}
                </td>

                <td>
                    {matches_text}
                </td>

                <td>
                    {esc(claimed_result)}
                </td>

                <td>
                    {esc(result_message_id)}
                </td>

                <td>
                    {esc(confidence)}
                </td>

                <td>
                    {esc(
                        verification_status
                    )}
                </td>
            </tr>
            """
        )

    return "".join(
        table_rows
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

    zero_match = (
        get_zero_match_coupons(
            conn
        )
    )

    multiple_results = (
        get_multiple_result_coupons(
            conn
        )
    )

    unlinked_results = (
        get_unlinked_results(
            conn
        )
    )

    all_coupons = (
        get_all_coupons(
            conn
        )
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    page = f"""
    <!DOCTYPE html>

    <html lang="tr">

    <head>

        <meta charset="utf-8">

        <title>
            JARVIS KARACA Deep Audit
        </title>

        <style>

            body {{
                font-family:
                    Arial,
                    sans-serif;

                max-width:
                    1600px;

                margin:
                    20px auto;

                background:
                    #111;

                color:
                    #eee;
            }}

            h1, h2, h3, h4 {{
                color:
                    #fff;
            }}

            .stats {{
                padding:
                    20px;

                background:
                    #181818;

                border:
                    1px solid #444;

                margin-bottom:
                    30px;
            }}

            .card {{
                padding:
                    20px;

                margin-bottom:
                    30px;

                background:
                    #181818;

                border:
                    1px solid #444;

                border-radius:
                    10px;
            }}

            .two {{
                display:
                    grid;

                grid-template-columns:
                    1fr 1fr;

                gap:
                    20px;
            }}

            img {{
                max-width:
                    100%;

                max-height:
                    900px;

                object-fit:
                    contain;

                background:
                    #000;
            }}

            pre {{
                white-space:
                    pre-wrap;

                word-break:
                    break-word;

                background:
                    #222;

                padding:
                    15px;
            }}

            .meta {{
                color:
                    #bbb;

                margin-bottom:
                    15px;
            }}

            .missing {{
                padding:
                    30px;

                background:
                    #300;
            }}

            table {{
                width:
                    100%;

                border-collapse:
                    collapse;

                font-size:
                    13px;
            }}

            th, td {{
                border:
                    1px solid #444;

                padding:
                    8px;

                vertical-align:
                    top;
            }}

            th {{
                background:
                    #252525;

                position:
                    sticky;

                top:
                    0;
            }}

        </style>

    </head>

    <body>

        <h1>
            JARVIS KARACA Deep Audit
        </h1>

        <div class="stats">

            <strong>
                Total primary coupons:
            </strong>

            {len(all_coupons)}

            <br>

            <strong>
                Zero-match coupons:
            </strong>

            {len(zero_match)}

            <br>

            <strong>
                Coupons with multiple
                result messages:
            </strong>

            {len(multiple_results)}

            <br>

            <strong>
                Unlinked result messages:
            </strong>

            {len(unlinked_results)}

        </div>


        <h2>
            1. ZERO-MATCH COUPONS
        </h2>

        <p>
            Parser'ın maç çıkaramadığı
            10 kupon burada.
            Bunların formatını inceleyerek
            parser'ı tek seferde düzelteceğiz.
        </p>

        {
            build_zero_match_section(
                zero_match
            )
        }


        <h2>
            2. MULTIPLE RESULT LINKS
        </h2>

        <p>
            Aynı primary kupona birden fazla
            sonuç mesajı bağlanan durumlar.
            Burada yanlış eşleşme olup olmadığını
            kontrol edeceğiz.
        </p>

        {
            build_multiple_result_section(
                conn,
                multiple_results,
            )
        }


        <h2>
            3. UNLINKED RESULT MESSAGES
        </h2>

        <p>
            COUPON_RESULT olarak sınıflanmış
            fakat hiçbir primary kupona
            bağlanamamış mesajlar.
        </p>

        {
            build_unlinked_section(
                unlinked_results
            )
        }


        <h2>
            4. ALL PRIMARY COUPONS
        </h2>

        <table>

            <thead>

                <tr>

                    <th>ID</th>

                    <th>
                        Primary Msg
                    </th>

                    <th>Date</th>

                    <th>Start</th>

                    <th>Odds</th>

                    <th>
                        Match Count
                    </th>

                    <th>Matches</th>

                    <th>
                        Claimed Result
                    </th>

                    <th>
                        Result Msg
                    </th>

                    <th>
                        Link Confidence
                    </th>

                    <th>
                        Verification
                    </th>

                </tr>

            </thead>

            <tbody>

                {
                    build_coupon_table(
                        conn,
                        all_coupons,
                    )
                }

            </tbody>

        </table>

    </body>

    </html>
    """

    REPORT_PATH.write_text(
        page,
        encoding="utf-8",
    )

    conn.close()

    print()
    print(
        "JARVIS KARACA DEEP AUDIT"
    )

    print("=" * 70)

    print(
        "Primary coupons:",
        len(all_coupons),
    )

    print(
        "Zero-match coupons:",
        len(zero_match),
    )

    print(
        "Coupons with multiple results:",
        len(multiple_results),
    )

    print(
        "Unlinked result messages:",
        len(unlinked_results),
    )

    print()

    print(
        "Report:",
        REPORT_PATH,
    )


if __name__ == "__main__":
    main()