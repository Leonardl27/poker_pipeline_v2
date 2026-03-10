# CLAUDE.md — Poker Pipeline V2

## Project Overview
Python ELT pipeline: JSON poker replay files -> SQLite -> Matplotlib charts -> self-contained HTML dashboard -> GitHub Pages.

## Key Commands
```bash
python generate_dashboard.py _site   # Build the dashboard
python verify_dashboard.py _site     # Build + validate (used by CI)
python verify_stats.py               # Compare HUD stats against known reference values
python main.py stats                 # Print database summary
python main.py unmapped              # List unmapped players
```

## Architecture
- SQLite DB is rebuilt from scratch on every run (no migrations needed)
- Charts are PNGs saved to `_site/`, then base64-embedded into `index.html`
- Dashboard is a single self-contained HTML file (no external JS/CSS)

## Adding a New Chart
1. Add query function + plot function in `visualize.py`
2. Register in `generate_all_visualizations()`
3. Add filename to `generate_chart_base64()` in `generate_dashboard.py`
4. Add tuple to `chart_configs` in `build_html()`

## Adding a New HUD Stat
1. Add accumulator keys in `calculate_hud_stats()` defaultdict in `hud_stats.py`
2. Add computation logic in the per-hand loop
3. Add percentage calculation in the results section
4. Wire into `get_table_data()` in `generate_dashboard.py`
5. Add to player profile HTML in `build_player_profiles_html()`
6. Add sanity check in `verify_dashboard.py`

## PokerNow Event Encoding
- BET (type 8) = actual raise/re-raise
- RAISE (type 7) = call/limp (matching current bet)
- CHECK_CALL (type 0) = check only
- ALL_IN (type 16) = all-in
- FOLD (type 11) = fold
- COMMUNITY_CARDS (type 9) = street boundary (flop/turn/river)
- SMALL_BLIND (type 3), BIG_BLIND (type 2)

## CI/CD Workflow

### On Push to Main
`deploy-dashboard.yml` runs `verify_dashboard.py` then deploys to GitHub Pages.
Verification must pass for deploy to proceed.

### On Pull Request to Main
`pr-preview.yml` runs `verify_dashboard.py` and posts results as a PR comment.
Bot comment shows pass/fail status with validation details.
Human must review the preview and approve before merge.

### Recommended Branch Protection (GitHub Settings > Branches > main)
- Require a pull request before merging
- Require 1 approval
- Require status checks to pass (`build-preview`)
- Require branches to be up to date before merging

## Dashboard Theme
- Background: #1a1a2e
- Panels: #16213e
- Accent: #e94560
- Positive: #4caf50
- Text: #eeeeee
- Border: #0f3460

## Settings
- `MIN_GAMES = 3` — minimum sessions to appear in dashboard
- Live URL: https://leonardl27.github.io/poker_pipeline_v2/
