import argparse
import json
import os
from pathlib import Path

import requests

BASE_URL = "https://api.football-data.org/v4"
LEAGUES = ["PL", "BL1", "SA", "PD", "FL1"]


def fetch_matches(competition, season, api_key):
    response = requests.get(
        f"{BASE_URL}/competitions/{competition}/matches",
        params={"season": season},
        headers={"X-Auth-Token": api_key},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument(
        "--league",
        choices=LEAGUES + ["ALL"],
        default="ALL",
    )
    args = parser.parse_args()

    api_key = os.getenv("FOOTBALL_DATA_API_KEY")
    if not api_key:
        raise SystemExit("FOOTBALL_DATA_API_KEY is missing")

    leagues = LEAGUES if args.league == "ALL" else [args.league]

    output_dir = Path("data/raw")
    output_dir.mkdir(parents=True, exist_ok=True)

    for league in leagues:
        data = fetch_matches(league, args.season, api_key)

        output_file = output_dir / f"{league}_{args.season}.json"
        output_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(
            league,
            len(data.get("matches", [])),
            output_file,
        )


if __name__ == "__main__":
    main()
