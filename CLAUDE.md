# CLAUDE.md — Poker Pipeline V2

## Project Overview
Python ELT pipeline: JSON poker replay files -> SQLite -> interactive SVG charts -> self-contained HTML dashboard -> GitHub Pages.

## Key Commands
```bash
python generate_dashboard.py _site   # Build the dashboard
python verify_dashboard.py _site     # Build + validate (used by CI)
python verify_stats.py               # Compare HUD stats against known reference values
python main.py stats                 # Print database summary
python main.py unmapped              # List unmapped players
```

## Agent Workflows
- Adding a new poker session (new replay in `raw/`): follow
  `.agents/skills/add-poker-session/SKILL.md`

## Architecture
- SQLite DB is rebuilt from scratch on every run (no migrations needed)
- Data charts are interactive inline SVG, rendered client-side by
  `static/charts.js` (inlined into `index.html` at build time) from the
  `CHART_DATA` JSON payload built by `chart_data.py`
- Architecture diagrams (pipeline/CI-CD) are matplotlib PNGs base64-embedded
  into `index.html`; the matplotlib data-chart functions in `visualize.py`
  remain for CLI use (`main.py`) only
- Page styles and interactions live in `static/dashboard.css` and
  `static/dashboard.js`, also inlined into `index.html` at build time
- Dashboard is a single self-contained HTML file (no external requests)
- Activity window: players with no session in the last `ACTIVE_WINDOW_DAYS`
  are left off the leaderboard, profiles and charts (`get_activity()` in
  `generate_dashboard.py`, `active_names` in `build_chart_data()`). Their data
  is never deleted; they're listed in the collapsed "Past Players" section and
  still count toward session/hand totals

## Adding a New Chart
1. Add a data builder function in `chart_data.py` and register it in
   `build_chart_data()` (plain Python types only — None for missing, no NaN)
2. Add a `render*` function in `static/charts.js` and a `go(...)` call in
   its bootstrap block
3. Add a `(div_id, title, description)` tuple to `chart_configs` in
   `build_html()` in `generate_dashboard.py`
4. Add the div id to `EXPECTED_CHART_DIVS` in `verify_dashboard.py`

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

### Branch Protection (applied on main via GitHub API, 2026-07-25)
- Require a pull request before merging (no direct pushes)
- Require the `build-preview` status check to pass
- Require branches to be up to date before merging
- Force pushes and branch deletion blocked
- 0 required approvals (solo repo — GitHub blocks self-approval, so requiring
  1 approval would make merging impossible); admins can bypass in a pinch

## Dashboard Theme
- Background: #1a1a2e
- Panels: #16213e
- Accent: #e94560
- Positive: #4caf50
- Text: #eeeeee
- Border: #0f3460

## Settings
- `MIN_GAMES = 3` — minimum sessions to appear in dashboard
- `ACTIVE_WINDOW_DAYS = 365` — must have played within this many days of the
  build to appear on the leaderboard/profiles/charts
- Live URL: https://leonardl27.github.io/poker_pipeline_v2/
