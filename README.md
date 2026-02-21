# Poker Pipeline V2

**Poker Analytics ELT Pipeline & Dashboard**

A data pipeline for processing poker hand history JSON replays into a normalized SQLite database, with player identity resolution and an auto-deployed static dashboard on GitHub Pages.

**[View Live Dashboard](https://leonardl27.github.io/poker_pipeline_v2/)**

## Features

- **ELT Pipeline**: Ingest poker match JSON replay files into a normalized SQLite database
- **Player Identity Resolution**: Map screen names and aliases to real player identities via a YAML configuration file
- **Statistical Visualizations**: Matplotlib-generated charts for player performance, hand distributions, session trends, and pot analysis
- **Auto-Deployed Dashboard**: Self-contained HTML dashboard deployed to GitHub Pages via GitHub Actions on every data update
- **Two-Layer Data Architecture**: Core hand data + enrichment layer for player identity mapping

## Project Structure

```
poker_pipeline_v2/
├── raw/                          # Place JSON replay files here
│   └── replay-pgl_*.json        # Poker hand history files
├── database.py                   # SQLite schema & connection management
├── ingest.py                     # JSON parsing & data ingestion
├── mappings.py                   # Player identity resolution
├── visualize.py                  # Matplotlib chart generation
├── main.py                       # CLI entry point
├── generate_dashboard.py         # Dashboard builder (pipeline + HTML generation)
├── player_map.yaml               # Player name mapping configuration
├── requirements.txt              # Python dependencies
├── .github/
│   └── workflows/
│       └── deploy-dashboard.yml  # GitHub Actions CI/CD workflow
└── .gitignore
```

## Installation

### Prerequisites

- Python 3.12 or higher
- pip

### Setup

```bash
git clone https://github.com/Leonardl27/poker_pipeline_v2.git
cd poker_pipeline_v2
pip install -r requirements.txt
```

## Usage

### Running the Full Pipeline Locally

Place JSON replay files in `raw/`, then run:

```bash
python main.py
```

This will:
1. Ingest all `*.json` files in the current directory
2. Print summary statistics
3. Generate visualization PNGs

### Individual Commands

```bash
# Ingest a single file
python main.py ingest replay-file.json

# Ingest all files in a directory
python main.py ingest raw/

# Generate visualizations from existing database
python main.py visualize

# Print database summary statistics
python main.py stats

# Load player identity mappings from YAML
python main.py load-mappings

# Load from a custom mapping file
python main.py load-mappings custom_map.yaml

# List players not yet mapped to canonical identities
python main.py unmapped

# Generate a YAML template from existing players
python main.py export-players
```

### Generating the Dashboard Locally

```bash
python generate_dashboard.py _site
```

This rebuilds the database from scratch, generates all charts, and produces a self-contained `_site/index.html` that can be opened in any browser.

## Automated Deployment

The GitHub Actions workflow automatically rebuilds and deploys the dashboard when:

- New JSON files are pushed to `raw/`
- `player_map.yaml` is updated
- Manually triggered via `workflow_dispatch`

### Pipeline Flow

```
JSON Replay Files (raw/)
        |
   [ingest.py] Parse & load into SQLite
        |
   [mappings.py] Apply player identity mappings
        |
   [visualize.py] Generate Matplotlib charts
        |
   [generate_dashboard.py] Build self-contained HTML
        |
   [GitHub Actions] Deploy to GitHub Pages
```

### One-Time Repository Setup

To enable automatic deployment, configure GitHub Pages:

1. Go to **Settings > Pages** in your repository
2. Set **Source** to **"GitHub Actions"**

## Player Identity Mapping

Players often use multiple screen names across sessions. The mapping system resolves these aliases to canonical player identities.

### Workflow

1. After ingesting new data, check for unmapped players:
   ```bash
   python main.py unmapped
   ```

2. Edit `player_map.yaml` to add aliases under the correct player:
   ```yaml
   canonical_players:
     - id: 1
       name: "Leonard Lange"
       aliases:
         - id: "mrmMdPuwc-"
           nickname: "Lenny"
         - id: "RXHdCYkC_S"
           nickname: "El Presidente"
   ```

3. Apply the mappings:
   ```bash
   python main.py load-mappings
   ```

4. Regenerate visualizations to see aggregated stats:
   ```bash
   python main.py visualize
   ```

To bootstrap a new mapping file from scratch:
```bash
python main.py export-players new_map.yaml
```

This generates a YAML template with every unique player as a separate entry, which you can then manually merge.

## Database Schema

The SQLite database uses a two-layer architecture:

### Core Data Layer

| Table | Purpose |
|-------|---------|
| `games` | Poker sessions (game ID, timestamps) |
| `hands` | Individual hands (blinds, ante, dealer seat) |
| `players` | Unique player identities (raw ID, screen name) |
| `hand_players` | Player state per hand (seat, stack, hole cards, net gain) |
| `events` | Actions within hands (check, call, bet, raise, fold, all-in) |
| `community_cards` | Board cards for each hand (flop, turn, river) |
| `hand_results` | Winners and hand strength (description, combination) |

### Enrichment Layer

| Table | Purpose |
|-------|---------|
| `canonical_players` | Real player identities (manually mapped) |
| `player_mappings` | Maps (raw_player_id, nickname) pairs to canonical players |

## Dashboard

The dashboard is a self-contained HTML file with:

- **Summary Cards**: Total sessions, hands, players, and events
- **Player Leaderboard**: Sortable table with profit/loss, win rate, games played (filtered to players with 3+ sessions)
- **Player Statistics**: Profit/loss, hands played, win rates, average profit per hand
- **Hand Analysis**: Winning hand distribution by category and action frequency
- **Session Trends**: All-time cumulative profit/loss with session boundary markers and pot sizes
- **Pipeline Architecture**: Visual diagram of the data flow

Charts are embedded as base64 PNG images, making the HTML file completely portable with no external dependencies.

## Configuration

### Player Mapping (`player_map.yaml`)

Maps screen name aliases to real player identities. See [Player Identity Mapping](#player-identity-mapping) above.

### Dashboard Settings (`generate_dashboard.py`)

| Setting | Default | Description |
|---------|---------|-------------|
| `DB_PATH` | `poker.db` | SQLite database file path |
| `RAW_DIR` | `raw` | Directory containing JSON replay files |
| `MAPPING_FILE` | `player_map.yaml` | Player identity mapping file |
| `OUTPUT_DIR` | `_site` | Dashboard output directory |
| `MIN_GAMES` | `3` | Minimum sessions for a player to appear on dashboard |

## Architecture Decisions

- **SQLite**: Simple, portable, zero-configuration database suitable for single-user analysis
- **ELT over ETL**: Raw event data is preserved in the database for reprocessing
- **Rebuild from scratch**: The CI pipeline rebuilds the database on every run for consistency
- **Self-contained HTML**: Dashboard uses inline CSS, embedded base64 images, and inline JavaScript with no external dependencies
- **Static over interactive**: GitHub Pages hosting is free and requires no server
- **Manual player mapping**: YAML-based identity resolution ensures accuracy over automatic fuzzy matching
- **Two-layer schema**: Core data layer for raw facts + enrichment layer for identity resolution allows flexible aggregation

## Development

### Adding New Visualizations

1. Add a data retrieval function in `visualize.py` (query the database)
2. Add a plot function in `visualize.py` (generate a Matplotlib figure)
3. Register it in `generate_all_visualizations()`
4. Add the chart to `generate_dashboard.py` in `chart_configs` and `generate_chart_base64()`

### Adding New Statistics

1. Add SQL queries to `visualize.py` data functions
2. Add columns to `get_table_data()` in `generate_dashboard.py`
3. Update the HTML table template in `build_html()`

## License

This project is for personal use.
