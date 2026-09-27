import argparse, csv, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def mean(xs):
    return sum(xs) / len(xs)


def poisson(k, lam):
    return math.exp(-lam) * lam**k / math.factorial(k)


def over25_prob(lam):
    return 1 - math.exp(-lam) * (1 + lam + lam * lam / 2)


def probs_1x2(lh, la, max_goals=10):
    h = d = a = 0.0

    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = poisson(i, lh) * poisson(j, la)

            if i > j:
                h += p
            elif i == j:
                d += p
            else:
                a += p

    return h, d, a


def load_matches(path, league, season):
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []

    for m in obj.get("matches", []):
        ft = (m.get("score") or {}).get("fullTime") or {}

        if (
            m.get("status") != "FINISHED"
            or ft.get("home") is None
            or ft.get("away") is None
        ):
            continue

        out.append(
            {
                "league": league,
                "season": season,
                "date": m["utcDate"],
                "home": m["homeTeam"]["name"],
                "away": m["awayTeam"]["name"],
                "hg": int(ft["home"]),
                "ag": int(ft["away"]),
            }
        )

    return out


def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--history-season", type=int, default=2023)
    ap.add_argument("--test-season", type=int, default=2024)
    ap.add_argument("--leagues", default="PL,BL1,SA,PD,FL1")
    ap.add_argument("--config", default="config/v1.json")
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--out-dir", default="reports")

    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    rows = []
    summary = []

    for league in args.leagues.split(","):
        hp = Path(args.raw_dir) / f"{league}_{args.history_season}.json"
        tp = Path(args.raw_dir) / f"{league}_{args.test_season}.json"

        if not hp.exists() or not tp.exists():
            summary.append(
                {
                    "league": league,
                    "status": "missing-data",
                    "history_file": str(hp),
                    "test_file": str(tp),
                }
            )
            continue

        history = sorted(
            load_matches(hp, league, args.history_season)
            + load_matches(tp, league, args.test_season),
            key=lambda x: dt(x["date"]),
        )

        test = [x for x in history if x["season"] == args.test_season]

        for m in test:

            # STRICT LEAKAGE PROTECTION:
            # only matches completed before this fixture
            before = [
                x
                for x in history
                if dt(x["date"]) < dt(m["date"])
            ]

            hh = [
                x for x in before
                if x["home"] == m["home"]
            ][-10:]

            aa = [
                x for x in before
                if x["away"] == m["away"]
            ][-10:]

            if len(hh) < 5 or len(aa) < 5:
                continue

            h5 = hh[-5:]
            a5 = aa[-5:]

            hgf = mean([x["hg"] for x in h5])
            hga = mean([x["ag"] for x in h5])

            agf = mean([x["ag"] for x in a5])
            aga = mean([x["hg"] for x in a5])

            lh = (hgf + aga) / 2
            la = (agf + hga) / 2

            total = lh + la

            actual_ou = (
                "O"
                if m["hg"] + m["ag"] > 2.5
                else "U"
            )

            actual_1x2 = (
                "H"
                if m["hg"] > m["ag"]
                else (
                    "A"
                    if m["hg"] < m["ag"]
                    else "D"
                )
            )

            # Legacy A
            r = lh * la

            # Legacy B
            e = (hgf + hga) / 2
            dep = (agf + aga) / 2
            r2 = e * dep

            pa = (
                "O"
                if r > cfg["legacy_a_threshold"]
                else "U"
            )

            pb = (
                "O"
                if r2 > cfg["legacy_b_threshold"]
                else "U"
            )

            # Poisson O/U
            pou = over25_prob(total)

            pp = (
                "O"
                if pou > cfg["poisson_ou_probability_threshold"]
                else "U"
            )

            # Poisson 1X2
            ph, pd, px = probs_1x2(
                lh,
                la,
                cfg["score_matrix_max_goals"],
            )

            p1 = (
                "H"
                if ph >= pd and ph >= px
                else (
                    "D"
                    if pd >= px
                    else "A"
                )
            )

            row = {
                "league": league,
                "date": m["date"],
                "home": m["home"],
                "away": m["away"],
                "hg": m["hg"],
                "ag": m["ag"],

                "lambda_home": lh,
                "lambda_away": la,

                "legacy_r": r,
                "legacy_r2": r2,

                "actual_ou": actual_ou,

                "legacy_a_ou": pa,
                "legacy_b_ou": pb,

                "poisson_ou": pp,
                "poisson_over_prob": pou,

                "actual_1x2": actual_1x2,
                "poisson_1x2": p1,

                "p_home": ph,
                "p_draw": pd,
                "p_away": px,
            }

            # L5 / L10
            if len(hh) >= 10 and len(aa) >= 10:

                lh10 = (
                    mean([x["hg"] for x in hh])
                    + mean([x["hg"] for x in aa])
                ) / 2

                la10 = (
                    mean([x["ag"] for x in aa])
                    + mean([x["ag"] for x in hh])
                ) / 2

                flh = (lh + lh10) / 2
                fla = (la + la10) / 2

                ftotal = flh + fla

                f_ou = (
                    "O"
                    if over25_prob(ftotal) > 0.5
                    else "U"
                )

                fh, fd, fa = probs_1x2(
                    flh,
                    fla,
                    cfg["score_matrix_max_goals"],
                )

                f1 = (
                    "H"
                    if fh >= fd and fh >= fa
                    else (
                        "D"
                        if fd >= fa
                        else "A"
                    )
                )

                row.update(
                    {
                        "form_ou": f_ou,
                        "form_1x2": f1,
                        "form_lambda_home": flh,
                        "form_lambda_away": fla,
                    }
                )

            # X & Under specialist
            xsel = (
                total <= cfg["x_under_total_lambda_max"]
                and abs(lh - la)
                <= cfg["x_under_lambda_gap_max"]
            )

            row["x_under_selected"] = xsel

            rows.append(row)

        lr = [
            r
            for r in rows
            if r["league"] == league
        ]

        n = len(lr)

        def acc(field, actual):
            valid = [
                r
                for r in lr
                if r.get(field) is not None
            ]

            if not valid:
                return None

            return round(
                100
                * sum(
                    r.get(field) == r.get(actual)
                    for r in valid
                )
                / len(valid),
                4,
            )

        summary.append(
            {
                "league": league,
                "raw_test": len(test),
                "evaluable_l5": n,

                "legacy_a_ou_acc":
                    acc("legacy_a_ou", "actual_ou"),

                "legacy_b_ou_acc":
                    acc("legacy_b_ou", "actual_ou"),

                "poisson_ou_acc":
                    acc("poisson_ou", "actual_ou"),

                "poisson_1x2_acc":
                    acc("poisson_1x2", "actual_1x2"),

                "form_ou_acc":
                    acc("form_ou", "actual_ou"),

                "form_1x2_acc":
                    acc("form_1x2", "actual_1x2"),

                "x_under_selected":
                    sum(
                        r["x_under_selected"]
                        for r in lr
                    ),
            }
        )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    (out / "summary.json").write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if rows:
        with (
            out / "predictions.csv"
        ).open(
            "w",
            newline="",
            encoding="utf-8",
        ) as f:

            fields = sorted(
                {
                    k
                    for r in rows
                    for k in r
                }
            )

            w = csv.DictWriter(
                f,
                fieldnames=fields,
            )

            w.writeheader()
            w.writerows(rows)

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
