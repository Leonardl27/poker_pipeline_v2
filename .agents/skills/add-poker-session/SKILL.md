---
name: add-poker-session
description: Load a new PokerNow replay JSON from raw/ into the poker dashboard - map new player aliases, verify the build, and open a PR to main. Use when the user says they added a new poker night / session / replay file.
---

# Add a poker session to the dashboard

The DB and dashboard are rebuilt from scratch from `raw/*.json` on every run,
so "loading" a session means: get the replay committed, make sure every alias
is mapped, prove the build passes, and merge via PR (main is protected; CI
deploys to GitHub Pages on merge).

## 1. Find the new file
```bash
git fetch origin
git status --short raw/          # new replay shows as untracked (??)
```
Confirm the session date from the file: hand `startedAt` is epoch ms (UTC).
Sessions are played in the evening US Central, so a UTC date one day later is
expected (e.g. a 9-18 night reads as 2026-09-19 UTC).

## 2. Branch off latest main
```bash
git checkout -b feature/add-<M-D-YY>-session origin/main
```
Never commit to main directly; branch protection requires a PR plus the
`build-preview` check.

## 3. Map new aliases
```bash
python main.py unmapped
```
For each unmapped (id, nickname):
- Same player id already in `player_map.yaml` -> add the nickname under that
  player (unambiguous).
- New id, but nickname matches an existing player (e.g. "Steel", "Marsh") ->
  add it under that player; players get new ids on new devices/accounts.
  Say which ones you mapped this way so the user can double-check.
- Nothing matches -> ask the user who it is (or add a new canonical player
  with the next id).

Aliases are keyed on the (id, nickname) pair, so each new pair gets its own
entry. Then `python main.py load-mappings` and re-run `unmapped` until it says
"All players are mapped!".

## 4. Verify
```bash
python verify_dashboard.py _site      # must print VERIFICATION PASSED
```
Sanity-check the session: per-player net for the new game should sum to 0
(group by player_id + nickname in `hand_players` joined to `hands.game_id`).
Watch for duplicate rows in `player_mappings` if you join through it.

## 5. Commit and PR
Commit only `raw/<new file>.json` and `player_map.yaml` (`poker.db` and
`_site/` are build outputs). Message convention:
`feat: add <M-D-YY> session results and map <N> new nicknames`
Push the branch and open a PR to main; merging deploys the dashboard to
https://leonardl27.github.io/poker_pipeline_v2/

## Gotchas
- **Line endings**: the repo lives on Windows with `core.autocrlf=true`. When
  running git from Linux/WSL/a VM over the same checkout, use
  `git -c core.autocrlf=true ...` or every file looks modified.
  Preserve CRLF when editing `player_map.yaml` programmatically.
- **scipy** is needed by `chart_data.py` (profit drivers); `pip install scipy`
  if the build fails with `ModuleNotFoundError`.
- `.claude/settings.local.json` and `.claude/worktrees/` are local - don't commit them.
