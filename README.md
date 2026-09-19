# JARVIS Football Backtest V1

Leakage-safe historical football backtesting for PL, Bundesliga, Serie A, La Liga and Ligue 1.

## Non-negotiable methodology
Predictions use only information available strictly before the fixture. Matches are processed chronologically. Missing odds are reported as unavailable and never synthesized. Thresholds are developed only on development data and then frozen for validation/test.

## V1 frozen rules
- Legacy-A threshold: R = 0.20
- Legacy-B threshold: R2 = 0.20
- Simple Poisson O/U probability threshold: 0.50
- L5/L10 form: fixed 50/50 blend
- X&Alt: total lambda <= 3.15 and absolute home-away lambda gap <= 0.45

These values must not be changed using 2024/25 holdout outcomes. A changed specification should be versioned as V2.

## API
The result/fixture ingestion layer uses football-data.org v4. Target competition codes are `PL`, `BL1`, `SA`, `PD`, `FL1`.

Never commit the API token. Add it as the GitHub Actions repository secret `FOOTBALL_DATA_API_KEY`.

## Historical odds
Odds are a separate source from the results API. Historical prices must retain source/bookmaker and pre-match timestamp semantics. If a price is unavailable, ROI is N/A for that observation.

## Run manually
```bash
pip install -r requirements.txt
export FOOTBALL_DATA_API_KEY=YOUR_KEY
python src/fetch_results.py --season 2024 --league ALL
```

## GitHub Actions
After adding the secret, open **Actions > Fetch football data > Run workflow** and enter the season start year (for 2024/25 use `2024`). The workflow fetches the five target leagues and commits timestamped source JSON to `data/raw/`.
