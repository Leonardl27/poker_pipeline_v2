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

## Hidden Amounts for Big Losers
Players whose lifetime loss exceeds `HIDE_LOSSES_OVER` ($400, in
`generate_dashboard.py`) keep their rank and stats, but none of their dollar
amounts are shown anywhere: leaderboard profit/avg-hand show a dash, no
profile header amount, latest-session seat shows hands instead, they're
skipped for records, and charts drop them from $-axis views (trend lines,
momentum, profit-driver points) or show attendance only (heatmap "played").
The set is `activity_info["private_names"]`; table rows carry `row["private"]`.
`check_private_amounts()` in `verify_dashboard.py` fails the build on any leak.
**Any new feature that displays money must respect this.**

## Adding a New Chart
1. Add a data builder function in `chart_data.py` and register it in
   `build_chart_data()` (plain Python types only — None for missing, no NaN)
2. Add a `render*` function in `static/charts.js` and a `go(...)` call in
   its bootstrap block
3. Add a `(div_id, title, description)` tuple to `chart_configs` in
   `build_html()` in `generate_dashboard.py`
4. Add the div id to `EXPECTED_CHART_DIVS` in `verify_dashboard.py`

## Player Advice ("How to improve")
`coaching.py` builds the per-player improvement section in each profile
(scouting.py is the opponent-facing counterpart). Each stat has a healthy
target band in `TARGETS`; leaks are ranked by distance outside the band x
weight (x1.5 when also worse than the table median), max one per area, and
stats need `MIN_SAMPLE` opportunities. Copy lives in `LEAK_TEXT` /
`STRENGTH_TEXT`. Sample counts come from `row["samples"]` in `get_table_data()`.

## Starting Hands Panel
`starting_hands.py` powers the 13x13 grid in each profile. Hole cards are
only known for the replay owner's hands, showdowns, and hands shown for fun,
so the sample is biased for most players:
- Cross-player comparison uses only hands turned face up (SHOW_CARDS) at
  showdown (`showdown_avg_pct`); the owner's mucked showdown hands are
  excluded so they're treated like everyone else.
- The play-vs-fold grid and fold metrics appear only when
  >= `FULL_FOLD_COVERAGE` of a player's folds are visible ("full" mode);
  otherwise the grid lights only hands seen played ("limited" mode).
- `HAND_EQUITY` is all-in equity vs. a random hand (seeded 40k-trial Monte
  Carlo with eval7, run once and committed); `HAND_PERCENTILE` is the
  combo-weighted "top X%" rank derived from it.

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
- `HIDE_LOSSES_OVER = 400` — hide every dollar amount for players whose
  lifetime loss is bigger than this
- `ACTIVE_WINDOW_DAYS = 365` — must have played within this many days of the
  build to appear on the leaderboard/profiles/charts
- Live URL: https://leonardl27.github.io/poker_pipeline_v2/
