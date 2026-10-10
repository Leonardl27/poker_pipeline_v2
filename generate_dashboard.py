"""
Dashboard generator for poker analytics.
Runs the full pipeline and produces a self-contained index.html for GitHub Pages.

Usage:
    python generate_dashboard.py [output_dir]
    python generate_dashboard.py _site
"""
import matplotlib
matplotlib.use('Agg')  # Must be set before any other matplotlib imports

import base64
import html as html_lib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Optional

from database import get_connection
from ingest import ingest_directory
from mappings import load_mappings
from visualize import (
    get_player_statistics, get_recent_session_avg_per_hand,
    get_latest_session_summary, get_player_activity, get_active_player_names,
    get_session_records, plot_pipeline_diagram, plot_cicd_diagram,
)
from hud_stats import calculate_hud_stats
from scouting import generate_scouting_report
from coaching import generate_coaching, table_medians, leak_gauge
from starting_hands import (
    build_starting_hands, grid_keys, HAND_PERCENTILE, TOP_PCT, JUNK_PCT,
    FULL_FOLD_COVERAGE,
)
from chart_data import build_chart_data

STATIC_DIR = Path(__file__).parent / "static"
CHART_JS_PATH = STATIC_DIR / "charts.js"
PAGE_JS_PATH = STATIC_DIR / "dashboard.js"
PAGE_CSS_PATH = STATIC_DIR / "dashboard.css"

DB_PATH = "poker.db"
RAW_DIR = "raw"
MAPPING_FILE = "player_map.yaml"
OUTPUT_DIR = "_site"
MIN_GAMES = 3  # Only show players who have played in at least this many sessions
# Players with no session in this many days drop off the leaderboard, profiles
# and charts. Their hands stay in the database and still count toward totals;
# they are listed in the collapsed "Past players" section instead.
ACTIVE_WINDOW_DAYS = 365
# Players whose lifetime loss is bigger than this keep their stats and rank,
# but no dollar amount of theirs is shown anywhere on the dashboard (tables,
# profiles, the latest-session table, records, chart tooltips/axes, or the
# page source). See get_private_names().
HIDE_LOSSES_OVER = 400


def run_pipeline(db_path: str = DB_PATH) -> dict:
    """Execute the full data pipeline and return summary statistics."""
    # Remove stale DB (rebuild from scratch)
    db_file = Path(db_path)
    if db_file.exists():
        db_file.unlink()

    # Ingest all JSON from raw/
    ingest_results = ingest_directory(RAW_DIR, db_path)

    # Load player identity mappings
    load_mappings(MAPPING_FILE, db_path)

    # Gather summary counts
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM games")
    total_games = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM hands")
    total_hands = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM canonical_players")
    total_players = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM events")
    total_events = cursor.fetchone()[0]

    cursor.execute("SELECT MIN(started_at) FROM hands")
    first_hand_ms = cursor.fetchone()[0]

    conn.close()

    return {
        "files_ingested": len(ingest_results),
        "total_games": total_games,
        "total_hands": total_hands,
        "total_players": total_players,
        "total_events": total_events,
        "first_hand_ms": first_hand_ms,
    }


def get_activity(db_path: str = DB_PATH, now: Optional[datetime] = None) -> dict:
    """Split players into active / past using ACTIVE_WINDOW_DAYS.

    Returns {"activity": {name: {...}}, "active_names": set,
             "cutoff_ms": int, "now_ms": int, "window_days": int}.
    Nothing is deleted: this only decides who is displayed.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ACTIVE_WINDOW_DAYS)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    activity = get_player_activity(db_path)
    return {
        "activity": activity,
        "active_names": get_active_player_names(activity, cutoff_ms),
        "private_names": get_private_names(activity),
        "cutoff_ms": cutoff_ms,
        "now_ms": int(now.timestamp() * 1000),
        "window_days": ACTIVE_WINDOW_DAYS,
    }


def get_private_names(activity: dict) -> set:
    """Players whose lifetime loss exceeds HIDE_LOSSES_OVER (amounts hidden)."""
    return {name for name, a in activity.items()
            if (a.get("profit") or 0) < -HIDE_LOSSES_OVER}


def get_past_players(activity_info: dict) -> list:
    """Players outside the active window (any number of sessions), newest first."""
    active = activity_info["active_names"]
    rows = [
        {"name": name, **a}
        for name, a in activity_info["activity"].items()
        if name not in active
    ]
    for r in rows:
        r["private"] = r["name"] in activity_info["private_names"]
    rows.sort(key=lambda r: r["last_played_ms"] or 0, reverse=True)
    return rows


def generate_chart_base64(db_path: str, output_dir: str) -> dict:
    """Generate the architecture diagram PNGs and return them base64-encoded.

    Data charts are no longer pre-rendered here — they are drawn client-side
    as interactive SVG from the CHART_DATA payload (see chart_data.py and
    static/charts.js). Only the two static architecture diagrams stay as PNGs.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    plot_pipeline_diagram(str(out / "pipeline_diagram.png"))
    plot_cicd_diagram(str(out / "cicd_diagram.png"))

    charts = {}
    for chart_name in ["pipeline_diagram.png", "cicd_diagram.png"]:
        chart_path = out / chart_name
        if chart_path.exists():
            with open(chart_path, "rb") as f:
                charts[chart_name] = base64.b64encode(f.read()).decode("utf-8")

    return charts


def get_table_data(db_path: str, active_names: Optional[set] = None) -> list:
    """Get player statistics formatted for the HTML leaderboard table.

    active_names: only include these players (None = compute the active set
    from ACTIVE_WINDOW_DAYS).
    """
    if active_names is None:
        active_names = get_activity(db_path)["active_names"]
    activity = get_player_activity(db_path)
    private_names = get_private_names(activity)

    stats = [r for r in get_player_statistics(db_path, use_enriched=True, min_games=MIN_GAMES)
             if r["name"] in active_names]

    # Get aggregate HUD stats (VPIP/PFR/ATS across all sessions)
    hud = calculate_hud_stats(db_path)
    hud_by_name = {h["name"]: h for h in hud}

    # Recent-session avg/hand trajectory (last 5 sessions per player)
    momentum_by_name = get_recent_session_avg_per_hand(db_path, n=5, min_games=MIN_GAMES)

    rows = []
    for row in stats:
        hands_played = row["hands_played"]
        hands_won = row["hands_won"] or 0
        total_profit = row["total_profit"] or 0
        avg_profit = row["avg_profit_per_hand"] or 0
        win_rate = (hands_won / hands_played * 100) if hands_played > 0 else 0

        # Merge HUD stats for this player
        h = hud_by_name.get(row["name"], {})

        rows.append({
            "name": row["name"],
            "games_played": row["games_played"],
            "hands_played": hands_played,
            "hands_won": hands_won,
            "win_rate": round(win_rate, 1),
            "total_profit": round(total_profit, 2),
            # True = lifetime loss over HIDE_LOSSES_OVER: never render $ amounts
            "private": row["name"] in private_names,
            "avg_profit": round(avg_profit, 2),
            "showdowns": row["showdowns"] or 0,
            "last_played_ms": activity.get(row["name"], {}).get("last_played_ms"),
            "vpip_pct": round(h.get("vpip_pct", 0), 1),
            "conv_vpip_pct": round(h.get("conv_vpip_pct", 0), 1),
            "pfr_pct": round(h.get("pfr_pct", 0), 1),
            "ats_pct": h.get("ats_pct"),
            # New profile stats
            "flop_seen_pct": round(h.get("flop_seen_pct", 0), 1),
            "bb_defend_pct": (round(h["bb_defend_pct"], 1)
                              if h.get("bb_defend_pct") is not None else None),
            "bb_fold_to_steal_pct": (round(h["bb_fold_to_steal_pct"], 1)
                                     if h.get("bb_fold_to_steal_pct") is not None else None),
            "three_bet_pct": (round(h["three_bet_pct"], 1)
                              if h.get("three_bet_pct") is not None else None),
            # Post-flop & showdown stats
            "wtsd_pct": (round(h["wtsd_pct"], 1)
                         if h.get("wtsd_pct") is not None else None),
            "wsd_pct": (round(h["wsd_pct"], 1)
                        if h.get("wsd_pct") is not None else None),
            "aggression_factor": (round(h["aggression_factor"], 1)
                                  if h.get("aggression_factor") is not None else None),
            "cbet_pct": (round(h["cbet_pct"], 1)
                         if h.get("cbet_pct") is not None else None),
            "fold_to_cbet_pct": (round(h["fold_to_cbet_pct"], 1)
                                 if h.get("fold_to_cbet_pct") is not None else None),
            "momentum": [v for _, v in momentum_by_name.get(row["name"], [])],
            # Opportunity counts behind each stat (coaching skips thin samples)
            "samples": {
                "hands": h.get("hands", hands_played),
                "three_bet_opportunities": h.get("three_bet_opportunities"),
                "flop_eligible_hands": h.get("flop_eligible_hands"),
                "bb_faced_raise_hands": h.get("bb_faced_raise_hands"),
                "bb_steal_faced_hands": h.get("bb_steal_faced_hands"),
                "ats_opportunities": h.get("ats_opportunities"),
                "postflop_actions": ((h.get("postflop_bets_raises") or 0)
                                     + (h.get("postflop_calls") or 0)),
                "cbet_opportunities": h.get("cbet_opportunities"),
                "faced_cbet": h.get("faced_cbet"),
                "flop_seen_hands": h.get("flop_seen_hands"),
                "showdown_hands": h.get("showdown_hands"),
            },
        })

    # Playing-style tag from the same VPIP/PFR median split as the
    # Player Archetypes chart
    if rows:
        vpip_med = median(r["conv_vpip_pct"] for r in rows)
        pfr_med = median(r["pfr_pct"] for r in rows)
        for r in rows:
            r["style"] = player_style(r["conv_vpip_pct"], r["pfr_pct"], vpip_med, pfr_med)
    return rows


# ---- small formatting helpers ------------------------------------------

STYLES = {
    # key: (label, css class, plain-English description)
    "shark": ("Shark", "style-shark", "tight-aggressive: picky with hands, raises when in"),
    "maniac": ("Maniac", "style-maniac", "loose-aggressive: plays lots of hands and raises often"),
    "rock": ("Rock", "style-rock", "tight-passive: few hands, mostly calls"),
    "station": ("Calling Station", "style-station", "loose-passive: plays lots of hands, mostly calls"),
}


def player_style(vpip: float, pfr: float, vpip_med: float, pfr_med: float) -> str:
    loose = vpip >= vpip_med
    aggressive = pfr >= pfr_med
    if aggressive:
        return "maniac" if loose else "shark"
    return "station" if loose else "rock"


def slugify(name: str) -> str:
    return name.lower().replace(" ", "-").replace("'", "")


def esc(s) -> str:
    return html_lib.escape(str(s), quote=True)


def money(v: float, cents: bool = True) -> str:
    fmt = "{:,.2f}" if cents else "{:,.0f}"
    if v > 0:
        return "+$" + fmt.format(v)
    if v < 0:
        return "-$" + fmt.format(abs(v))
    return "$0" + (".00" if cents else "")


def fmt_date(ms: Optional[int], fmt: str = "%b %d, %Y") -> str:
    if not ms:
        return "Unknown"
    try:
        return datetime.fromtimestamp(ms / 1000).strftime(fmt)
    except (ValueError, TypeError, OSError):
        return "Unknown"


def time_ago(ms: Optional[int], now_ms: int) -> str:
    """Rough human phrase for how long ago a timestamp was."""
    if not ms:
        return "unknown"
    days = (now_ms - ms) / 86_400_000
    if days < 7:
        return "this week"
    if days < 14:
        return "last week"
    if days < 60:
        return f"{int(days // 7)} weeks ago"
    if days < 365:
        return f"{int(days // 30)} months ago"
    years = days / 365
    return "over a year ago" if years < 2 else f"{int(years)} years ago"


def _stat_bar_color(stat_name: str, value: float) -> str:
    """Return a CSS color for a stat bar based on poker stat ranges."""
    ranges = {
        "vpip":     [(25, "#5b9bd5"), (40, "#4caf50"), (100, "#e94560")],
        "pfr":      [(10, "#5b9bd5"), (20, "#4caf50"), (100, "#e94560")],
        "three_bet":[(5,  "#5b9bd5"), (10, "#4caf50"), (100, "#e94560")],
        "flop_seen":[(40, "#5b9bd5"), (60, "#4caf50"), (100, "#e94560")],
        "bb_defend":[(40, "#e94560"), (60, "#4caf50"), (100, "#5b9bd5")],
        "bb_fold":  [(30, "#4caf50"), (50, "#e9a945"), (100, "#e94560")],
        "ats":      [(25, "#5b9bd5"), (40, "#4caf50"), (100, "#e94560")],
        "wtsd":     [(20, "#5b9bd5"), (35, "#4caf50"), (100, "#e94560")],
        "wsd":      [(45, "#e94560"), (55, "#4caf50"), (100, "#5b9bd5")],
        "cbet":     [(50, "#5b9bd5"), (70, "#4caf50"), (100, "#e94560")],
        "fold_cbet":[(40, "#4caf50"), (55, "#e9a945"), (100, "#e94560")],
    }
    thresholds = ranges.get(stat_name, [(100, "#4caf50")])
    for limit, color in thresholds:
        if value <= limit:
            return color
    return thresholds[-1][1]


def _momentum_sparkline_svg(values: list, width: int = 110, height: int = 32,
                            show_values: bool = True) -> str:
    """Render a small inline-SVG sparkline of avg/hand values with a trend arrow.

    Each session is a point connected by a polyline; points are colored green if
    positive, red if negative. A trend arrow compares the last value to the first.
    """
    if not values:
        return '<span class="momentum-na" title="Fewer than 1 recorded session">--</span>'

    pad = 3
    n = len(values)
    vmin = min(values)
    vmax = max(values)
    # Symmetric around zero so the baseline is meaningful
    bound = max(abs(vmin), abs(vmax), 0.01)
    lo, hi = -bound, bound

    def x(i):
        if n == 1:
            return width / 2
        return pad + (width - 2 * pad) * (i / (n - 1))

    def y(v):
        # Map [lo, hi] -> [height-pad, pad]  (higher value = higher on chart)
        frac = (v - lo) / (hi - lo) if hi > lo else 0.5
        return height - pad - frac * (height - 2 * pad)

    zero_y = y(0)
    points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    circles = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.2" fill="{"#4caf50" if v >= 0 else "#e94560"}" />'
        for i, v in enumerate(values)
    )

    # Trend arrow: compare last to first (or last to mean if only 1 point)
    if n >= 2:
        delta = values[-1] - values[0]
    else:
        delta = values[-1]
    if delta > 0.05:
        arrow, arrow_color = "↑", "#4caf50"
    elif delta < -0.05:
        arrow, arrow_color = "↓", "#e94560"
    else:
        arrow, arrow_color = "→", "#aaaaaa"

    if show_values:
        title = f"Last {n} sessions avg/hand: " + ", ".join(f"{v:+.2f}" for v in values)
    else:
        title = f"Trend over the last {n} sessions"

    return (
        f'<span class="momentum-cell" title="{title}">'
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="{pad}" y1="{zero_y:.1f}" x2="{width - pad}" y2="{zero_y:.1f}" '
        f'stroke="#0f3460" stroke-width="1" stroke-dasharray="2,2" />'
        f'<polyline points="{points}" fill="none" stroke="#5b9bd5" stroke-width="1.5" />'
        f'{circles}'
        f'</svg>'
        f'<span class="momentum-arrow" style="color:{arrow_color}">{arrow}</span>'
        f'</span>'
    )


def _target_label(leak: dict) -> str:
    low, high = leak["low"], leak["high"]
    if leak["key"] == "aggression_factor":
        return f"{low:g}\u2013{high:g}"
    if high >= 100:
        return f"{low:g}%+"
    return f"{low:g}\u2013{high:g}%"


def build_coaching_html(row: dict, medians: dict) -> str:
    """'How to improve' block: headline, top leaks with gauges, strengths."""
    coaching = generate_coaching(row, medians)
    first = esc(row["name"].split()[0])
    is_af = lambda leak: leak["key"] == "aggression_factor"

    cards = ""
    for leak in coaching["leaks"]:
        g = leak_gauge(leak)
        med = leak.get("median")
        med_label = (f"{med:.1f}" if is_af(leak) else f"{med:.0f}%") if med is not None else "n/a"
        med_mark = (f'<span class="g-med" style="left:{g["median"]:.1f}%"></span>'
                    if g["median"] is not None else "")
        aria = (f'{esc(leak["label"])}: {first} {leak["value_label"]}, table {med_label}, '
                f'target {_target_label(leak)}')
        cards += f'''
                            <article class="leak">
                                <h5>{esc(leak["title"])}</h5>
                                <div class="gauge-label">{esc(leak["label"])}</div>
                                <div class="gauge" role="img" aria-label="{aria}">
                                    <span class="g-band" style="left:{g["band_left"]:.1f}%;width:{g["band_right"] - g["band_left"]:.1f}%"></span>
                                    {med_mark}
                                    <span class="g-you" style="left:{g["you"]:.1f}%"></span>
                                </div>
                                <div class="gauge-legend">
                                    <span class="lg-you">{first} {leak["value_label"]}</span>
                                    <span class="lg-med">Table {med_label}</span>
                                    <span class="lg-band">Target {_target_label(leak)}</span>
                                </div>
                                <p class="leak-why">{esc(leak["why"])}</p>
                                <p class="leak-try"><strong>Try this:</strong> {esc(leak["try"])}</p>
                            </article>'''

    if not cards:
        cards = ('<p class="leak-none">No big leaks stand out in the numbers. '
                 'Keep doing what you\'re doing and focus on reading opponents.</p>')

    strengths = ""
    if coaching["strengths"]:
        items = "".join(f"<li>{esc(t)}</li>" for t in coaching["strengths"])
        strengths = f'<div class="strengths"><h5>What\'s working</h5><ul>{items}</ul></div>'

    return f'''
                    <div class="coaching">
                        <h4>How to improve</h4>
                        <p class="coaching-headline">{esc(coaching["headline"])}</p>
                        <div class="leaks">{cards}
                        </div>
                        {strengths}
                    </div>'''


def _mix(c1: tuple, c2: tuple, t: float) -> str:
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


_FOLD_RGB = (34, 48, 84)      # always folded
_PLAY_RGB = (233, 169, 69)    # always played (gold)


def build_starting_hands_html(name: str, sh: Optional[dict], table: dict) -> str:
    """'Starting hands' panel: 13x13 grid + coverage + strength metrics.

    Full mode (most folds visible): each cell is colored by how often they
    played that hand vs. folded it. Limited mode: only hands we've seen them
    play are lit, since their folds are mostly hidden. No dollar amounts.
    """
    if not sh:
        return ""
    first = esc(name.split()[0])
    full, cells = sh["full"], sh["cells"]
    max_seen = max((c["played"] for c in cells.values()), default=1) or 1

    grid = ""
    for row in grid_keys():
        for key in row:
            c = cells.get(key, {"played": 0, "folded": 0})
            p, f = c["played"], c["folded"]
            strong = " strong" if HAND_PERCENTILE[key] <= TOP_PCT else ""
            if full and p + f:
                rate = p / (p + f)
                bg = _mix(_FOLD_RGB, _PLAY_RGB, rate)
                tip = f"{key}: played {p} of {p + f} times we saw it"
                dark = rate > 0.55
            elif not full and p:
                t = (p / max_seen) ** 0.5
                bg = _mix(_FOLD_RGB, _PLAY_RGB, 0.25 + 0.75 * t)
                tip = f"{key}: seen played {p} time{'s' if p != 1 else ''}"
                dark = t > 0.45
            else:
                bg, tip, dark = "", f"{key}: not seen", False
            style = f' style="background:{bg}"' if bg else ""
            cls = f"hc{strong}{' lit' if bg else ''}{' ink' if dark else ''}"
            grid += f'<span class="{cls}"{style} title="{tip}">{key}</span>'

    # Coverage meter
    coverage = f'''
                            <div class="hands-coverage">
                                <div class="cov-row"><span>Hands played we can see</span><span class="cov-bar"><span style="width:{sh['played_coverage']}%"></span></span><span>{sh['played_coverage']}%</span></div>
                                <div class="cov-row"><span>Folds we can see</span><span class="cov-bar"><span style="width:{sh['folded_coverage']}%"></span></span><span>{sh['folded_coverage']}%</span></div>
                            </div>'''

    facts = []
    sd, tsd = sh.get("showdown_avg_pct"), table.get("showdown_avg_pct")
    if sd is not None:
        if tsd is not None and sd < tsd - 2:
            cmp = f"stronger than the table median (top {tsd}%)"
        elif tsd is not None and sd > tsd + 2:
            cmp = f"weaker than the table median (top {tsd}%)"
        else:
            cmp = f"about the table median (top {tsd}%)"
        facts.append(("At showdown", f"top {sd}%",
                      f"Average starting hand across {sh['showdown_seen']} hands shown at showdown, {cmp}. "
                      "This is the fair comparison: everyone has to show here."))
    if full:
        if sh["avg_played_pct"] is not None:
            facts.append(("Every hand played", f"top {sh['avg_played_pct']}%",
                          f"Average starting hand across all {sh['seen_played']:,} hands we saw {first} play."))
        if sh["weak_fold_rate"] is not None:
            facts.append(("Weak hands folded", f"{sh['weak_fold_rate']}%",
                          f"Of the bottom-half hands {first} was dealt. Disciplined players fold most of these."))
        if sh["strong_play_rate"] is not None:
            facts.append(("Strong hands played", f"{sh['strong_play_rate']}%",
                          f"Of top-{TOP_PCT}% hands dealt. Folding these gives away value."))
    facts_html = "".join(
        f'<div class="hfact"><div class="hfact-label">{label}</div>'
        f'<div class="hfact-value">{value}</div><div class="hfact-note">{note}</div></div>'
        for label, value, note in facts
    )

    if not sh["enough"]:
        mode_note = (f"Not enough of {first}'s hands have been shown yet. The grid fills in "
                     f"as more hands reach showdown or get shown for fun.")
    elif full:
        mode_note = (f"We can see most of {first}'s folds, so each square shows how often "
                     f"{first} played that hand when dealt it.")
    else:
        mode_note = (f"Most of {first}'s folds stay hidden, so the grid only lights up hands we've "
                     f"seen {first} play (mostly showdowns and hands shown for fun). That leans "
                     f"toward stronger hands, so compare players using the showdown figure.")

    if full:
        legend = ('<span class="lg-scale"><span class="lg-chip" style="background:%s"></span>Always folded'
                  '<span class="lg-grad"></span><span class="lg-chip" style="background:%s"></span>Always played</span>'
                  % (_mix(_FOLD_RGB, _PLAY_RGB, 0), _mix(_FOLD_RGB, _PLAY_RGB, 1)))
    else:
        legend = ('<span class="lg-scale"><span class="lg-chip" style="background:%s"></span>Seen played'
                  '<span class="lg-grad"></span><span class="lg-chip" style="background:%s"></span>Seen often</span>'
                  % (_mix(_FOLD_RGB, _PLAY_RGB, 0.25), _mix(_FOLD_RGB, _PLAY_RGB, 1)))
    legend += '<span><span class="lg-strong"></span>Top 20% of starting hands</span>'

    return f'''
                    <div class="hands-panel" data-mode="{'full' if full else ('limited' if sh['enough'] else 'thin')}">
                        <h4>Starting hands</h4>
                        <p class="hands-lede">{mode_note}</p>
                        <div class="hands-layout">
                            <div>
                                <div class="hand-grid" aria-label="Starting hand grid for {esc(name)}">{grid}</div>
                                <div class="hands-legend">{legend}</div>
                                <p class="grid-key">Pairs run down the diagonal, suited hands sit above it and offsuit hands below.</p>
                            </div>
                            <div class="hands-side">
                                {coverage}
                                <div class="hfacts">{facts_html}</div>
                            </div>
                        </div>
                    </div>'''


def build_player_profiles_html(table_data: list, now_ms: Optional[int] = None,
                               starting_hands: Optional[dict] = None) -> str:
    """Generate collapsible player profile cards."""
    now_ms = now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    medians = table_medians(table_data)
    profiles = ""
    for row in table_data:
        name = row["name"]
        slug = slugify(name)
        profit = row["total_profit"]
        profit_class = "positive" if profit >= 0 else "negative"
        profit_span = ("" if row.get("private") else
                       f'<span class="{profit_class}">{money(profit)}</span>')

        # Build stat rows for each category
        def stat_row(label, value, stat_key, suffix="%"):
            if value is None:
                return f'''<div class="stat-row">
                        <span class="stat-label">{label}</span>
                        <div class="stat-bar-container"><div class="stat-bar" style="width:0%;"></div></div>
                        <span class="stat-value stat-na">--</span>
                    </div>'''
            color = _stat_bar_color(stat_key, value)
            width = min(value, 100)
            return f'''<div class="stat-row">
                        <span class="stat-label">{label}</span>
                        <div class="stat-bar-container"><div class="stat-bar" style="width:{width}%; background:{color};"></div></div>
                        <span class="stat-value">{value:.1f}{suffix}</span>
                    </div>'''

        preflop_stats = (
            stat_row("VPIP%", row["conv_vpip_pct"], "vpip")
            + stat_row("PFR%", row["pfr_pct"], "pfr")
            + stat_row("3-Bet%", row["three_bet_pct"], "three_bet")
            + stat_row("Flop Seen%", row["flop_seen_pct"], "flop_seen")
        )

        bb_stats = (
            stat_row("BB Defense%", row["bb_defend_pct"], "bb_defend")
            + stat_row("BB Fold to Steal%", row["bb_fold_to_steal_pct"], "bb_fold")
        )

        steal_stats = stat_row("ATS%", row["ats_pct"], "ats")

        # AF is a ratio (not percentage) — needs special rendering
        def ratio_row(label, value, max_scale=5.0):
            if value is None:
                return f'''<div class="stat-row">
                        <span class="stat-label">{label}</span>
                        <div class="stat-bar-container"><div class="stat-bar" style="width:0%;"></div></div>
                        <span class="stat-value stat-na">--</span>
                    </div>'''
            width = min(value / max_scale * 100, 100)
            color = "#5b9bd5" if value < 1.5 else "#4caf50" if value < 3.5 else "#e94560"
            return f'''<div class="stat-row">
                        <span class="stat-label">{label}</span>
                        <div class="stat-bar-container"><div class="stat-bar" style="width:{width}%; background:{color};"></div></div>
                        <span class="stat-value">{value:.1f}</span>
                    </div>'''

        postflop_stats = (
            stat_row("C-Bet%", row["cbet_pct"], "cbet")
            + stat_row("Fold to C-Bet%", row["fold_to_cbet_pct"], "fold_cbet")
            + ratio_row("Aggression Factor", row["aggression_factor"])
        )

        showdown_stats = (
            stat_row("WTSD%", row["wtsd_pct"], "wtsd")
            + stat_row("W$SD%", row["wsd_pct"], "wsd")
        )

        scouting_bullets = generate_scouting_report(row)
        scouting_li = "\n                            ".join(
            f"<li>{b}</li>" for b in scouting_bullets
        )

        style_key = row.get("style")
        style_tag = ""
        if style_key:
            label, cls, desc = STYLES[style_key]
            style_tag = f'<span class="style-tag {cls}" title="{esc(desc)}">{label}</span>'

        profiles += f'''
            <div class="player-profile" id="profile-{slug}">
                <button class="profile-header" id="profile-btn-{slug}" type="button"
                        aria-expanded="false" aria-controls="profile-body-{slug}"
                        onclick="toggleProfile('{slug}')">
                    <span class="profile-title"><h3>{esc(name)}</h3>{style_tag}</span>
                    <span class="profile-summary">
                        <span>{row['games_played']} sessions, {row['hands_played']:,} hands</span>
                        <span>Last played {time_ago(row.get('last_played_ms'), now_ms)}</span>
                        {profit_span}
                        <span class="chev" aria-hidden="true">&#9656;</span>
                    </span>
                </button>
                <div class="profile-body" id="profile-body-{slug}">
                    {build_coaching_html(row, medians)}
                    {build_starting_hands_html(name, (starting_hands or {}).get(name), (starting_hands or {}).get("_table", {}))}
                    <h4 class="breakdown-title">Full stat breakdown</h4>
                    <div class="profile-stats-grid">
                        <div class="stat-category">
                            <h4>Preflop Tendencies</h4>
                            {preflop_stats}
                        </div>
                        <div class="stat-category">
                            <h4>Big Blind Play</h4>
                            {bb_stats}
                        </div>
                        <div class="stat-category">
                            <h4>Steal Game</h4>
                            {steal_stats}
                        </div>
                        <div class="stat-category">
                            <h4>Postflop Play</h4>
                            {postflop_stats}
                        </div>
                        <div class="stat-category">
                            <h4>Showdown</h4>
                            {showdown_stats}
                        </div>
                    </div>
                    <div class="scouting-report">
                        <h4>Scouting Report</h4>
                        <ul class="scouting-bullets">
                            {scouting_li}
                        </ul>
                    </div>
                </div>
            </div>'''

    return f'''
        <section class="player-profiles-section" id="profiles">
            <h2 class="section-title">Player Profiles</h2>
            <p class="profiles-hint">Each card shows how that player can improve, their full stats, and how opponents can play against them. Open a card here, or click a name in the leaderboard.</p>
            <div class="profile-grid">{profiles}
            </div>
        </section>'''


def build_latest_session_html(latest: dict, profile_slugs: Optional[set] = None,
                              records: Optional[dict] = None,
                              private_names: Optional[set] = None) -> str:
    """The 'Latest Session' hero: everyone seated around a poker table.

    Seats go clockwise from the top in finishing order, so the night's
    winner sits at the head of the table.
    """
    if not latest or not latest.get("players"):
        return ""
    import math

    profile_slugs = profile_slugs or set()
    private_names = private_names or set()
    players = latest["players"]
    n = len(players)

    seats = ""
    for i, p in enumerate(players):
        angle = math.radians(-90 + i * 360 / n)
        left = 50 + 50 * math.cos(angle)
        top = 50 + 50 * math.sin(angle)
        cls = "positive" if p["profit"] >= 0 else "negative"
        winner = " winner" if i == 0 and p["profit"] > 0 else ""
        if p["name"] in private_names:
            # No dollar amount: show hands played in the amount slot instead
            amount_html = f'<span class="seat-amount seat-private">{p["hands"]} hands</span>'
        else:
            amount_html = (f'<span class="seat-amount {cls}">{money(p["profit"])}</span>\n'
                           f'                        <span class="seat-hands">{p["hands"]} hands</span>')
        slug = slugify(p["name"])
        attrs = (f' onclick="showProfile(\'{slug}\')" title="Open {esc(p["name"])}\'s profile"'
                 if slug in profile_slugs else ' tabindex="-1"')
        seats += f'''
                    <button type="button" class="seat{winner}" style="left:{left:.2f}%;top:{top:.2f}%;animation-delay:{i * 70}ms"{attrs}>
                        <span class="seat-name">{esc(p['name'])}</span>
                        {amount_html}
                    </button>'''

    return f'''
        <section class="latest-session" id="latest">
            <h2 class="section-title">Latest Session</h2>
            <p class="section-lede">How the most recent night shook out, from the biggest winner at the head of the table around to the toughest night.</p>
            <div class="table-stage">
                <div class="felt">
                    <div class="felt-center">
                        <span class="felt-mark" aria-hidden="true">&#9824;&#xFE0E; &#9829;&#xFE0E; &#9827;&#xFE0E; &#9830;&#xFE0E;</span>
                        <span class="felt-date">{esc(latest['date_label'])}</span>
                        <span class="felt-meta">{n} players, {latest['hands_dealt']} hands dealt</span>
                    </div>{seats}
                </div>
            </div>
            {build_records_html(records)}
        </section>'''


def build_records_html(records: Optional[dict]) -> str:
    """All-time records strip shown under the latest-session table."""
    if not records:
        return ""
    items = []
    best = records.get("best_night")
    if best:
        items.append(("Biggest night ever", f'<span class="positive">{money(best["amount"])}</span>',
                      f'{esc(best["name"])}, {best["date"]}'))
    worst = records.get("worst_night")
    if worst:
        items.append(("Roughest night ever", f'<span class="negative">{money(worst["amount"])}</span>',
                      f'{esc(worst["name"])}, {worst["date"]}'))
    pot = records.get("biggest_pot")
    if pot:
        items.append(("Biggest pot", f'${pot["amount"]:,.2f}', pot["date"]))
    streak = records.get("hot_streak")
    if streak:
        items.append(("Hottest streak right now", f'{streak["count"]} wins in a row',
                      esc(streak["name"])))
    if not items:
        return ""
    cells = "".join(
        f'<div class="record"><div class="record-label">{label}</div>'
        f'<div class="record-value">{value}</div><div class="record-detail">{detail}</div></div>'
        for label, value, detail in items
    )
    return f'<div class="records">{cells}</div>'


def build_leaderboard_html(table_data: list, now_ms: int) -> str:
    """Sortable, searchable leaderboard. Advanced columns hide behind a toggle."""
    max_abs = max((abs(r["total_profit"]) for r in table_data if not r.get("private")),
                  default=1) or 1

    def signed(v):
        return f"+{v:.2f}" if v > 0 else f"{v:.2f}"

    rows = ""
    for rank, row in enumerate(table_data, start=1):
        slug = slugify(row["name"])
        profit = row["total_profit"]
        p_cls = "positive" if profit >= 0 else "negative"
        a_cls = "positive" if row["avg_profit"] >= 0 else "negative"
        bar_w = abs(profit) / max_abs * 50  # half the bar each side of zero
        bar = (f'<span class="up" style="width:{bar_w:.1f}%"></span>' if profit >= 0
               else f'<span class="down" style="width:{bar_w:.1f}%"></span>')
        private = row.get("private", False)
        if private:
            # Lifetime loss over HIDE_LOSSES_OVER: no amount, no bar, no raw value.
            # Empty data-sort sorts lowest, which matches their rank anyway.
            profit_td = ('<td class="num profit-cell" data-sort=""><span class="profit-wrap">'
                         '<span class="profit-num private-amt" title="Amount not shown">&mdash;</span></span></td>')
            avg_td = '<td class="num" data-sort=""><span class="private-amt" title="Amount not shown">&mdash;</span></td>'
        else:
            profit_td = (f'<td class="num profit-cell" data-sort="{profit}"><span class="profit-wrap">'
                         f'<span class="pbar">{bar}</span><span class="profit-num {p_cls}">{signed(profit)}</span></span></td>')
            avg_td = f'<td class="num {a_cls}" data-sort="{row["avg_profit"]}">{signed(row["avg_profit"])}</td>'
        trend = (row["momentum"][-1] - row["momentum"][0]) if len(row["momentum"]) >= 2 else 0
        ats = row["ats_pct"]
        style_tag = ""
        if row.get("style"):
            label, cls, desc = STYLES[row["style"]]
            style_tag = f'<span class="style-tag {cls}" title="{esc(desc)}">{label}</span>'
        row_class = f' class="top-{rank}"' if rank <= 3 else ""
        badge_class = f"rank-badge rank-{rank}" if rank <= 3 else "rank-badge"
        last_ms = row.get("last_played_ms") or 0

        rows += f"""
                    <tr{row_class} data-slug="{slug}" data-name="{esc(row['name'].lower())}" tabindex="0" title="Open {esc(row['name'])}'s profile">
                        <td class="rank-cell" data-sort="{rank}"><span class="{badge_class}">{rank}</span></td>
                        <td class="player-cell" data-sort="{esc(row['name'])}">
                            <div class="player-name">{esc(row['name'])}</div>
                            <div class="player-sub">{style_tag}<span class="last-played">Played {time_ago(last_ms, now_ms)}</span></div>
                        </td>
                        <td class="num">{row['games_played']}</td>
                        <td class="num" data-sort="{row['hands_played']}">{row['hands_played']:,}</td>
                        {profit_td}
                        {avg_td}
                        <td class="num" data-sort="{row['win_rate']}">{row['win_rate']:.1f}%</td>
                        <td class="num" data-sort="{row['conv_vpip_pct']}">{row['conv_vpip_pct']:.1f}%</td>
                        <td class="num" data-sort="{row['pfr_pct']}">{row['pfr_pct']:.1f}%</td>
                        <td data-sort="{trend:.4f}">{_momentum_sparkline_svg(row['momentum'], show_values=not private)}</td>
                        <td class="num adv">{row['hands_won']}</td>
                        <td class="num adv" data-sort="{row['vpip_pct']}">{row['vpip_pct']:.1f}%</td>
                        <td class="num adv" data-sort="{ats if ats is not None else ''}">{f"{ats:.1f}%" if ats is not None else "-"}</td>
                        <td class="num adv">{row['showdowns']}</td>
                        <td class="num adv" data-sort="{last_ms}">{fmt_date(last_ms, "%b %d, %Y")}</td>
                    </tr>"""

    headers = [
        ("#", "number", "Rank by lifetime profit", "", ' data-first="ascending"'),
        ("Player", "string", "", "", ""),
        ("Sessions", "number", "Sessions played", "num", ""),
        ("Hands", "number", "Hands dealt in", "num", ""),
        ("Profit/loss", "number", "Lifetime profit or loss in dollars", "num", ""),
        ("Avg/hand", "number", "Average dollars won or lost per hand", "num", ""),
        ("Win rate", "number", "Share of hands won", "num", ""),
        ("VPIP", "number", "Voluntarily put money in the pot preflop: how many hands they play", "num", ""),
        ("PFR", "number", "Preflop raise: how often they raise before the flop", "num", ""),
        ("Momentum", "number", "Avg/hand over the last 5 sessions; sorts by trend (newest minus oldest)", "", ""),
        ("Wins", "number", "Hands won", "num adv", ""),
        ("PN VPIP", "number", "PokerNow VPIP: voluntary money on any street", "num adv", ""),
        ("ATS", "number", "Attempt to steal: raises first in from late position", "num adv", ""),
        ("Showdowns", "number", "Times they showed cards", "num adv", ""),
        ("Last played", "number", "Date of their most recent session", "num adv", ""),
    ]
    ths = ""
    for i, (label, typ, tip, cls, extra) in enumerate(headers):
        title = f' title="{esc(tip)}"' if tip else ""
        ths += (f'<th class="sortable {cls}" scope="col" tabindex="0" data-col="{i}" '
                f'data-type="{typ}"{extra}{title}>{label}<span class="arrow" aria-hidden="true">&#8597;</span></th>')

    count_label = f"{len(table_data)} active players"
    return f'''
        <section class="table-section" id="leaderboard">
            <h2 class="section-title">Player Leaderboard</h2>
            <p class="section-lede">Everyone with {MIN_GAMES}+ sessions who has played in the last 12 months, ranked by lifetime profit. Click a column to sort, or a player to open their profile.</p>
            <div class="board-tools">
                <input id="playerSearch" class="search" type="search" placeholder="Find a player" aria-label="Find a player">
                <button id="advToggle" class="btn" type="button" aria-pressed="false">Show more stats</button>
                <span id="boardCount" class="board-count" data-default="{count_label}">{count_label}</span>
            </div>
            <div class="table-scroll" id="board">
                <table id="playerTable">
                    <thead><tr>{ths}</tr></thead>
                    <tbody>{rows}
                    </tbody>
                </table>
                <p class="no-match" id="noMatch">No active player matches that name.</p>
            </div>
            <details class="glossary">
                <summary>What do these stats mean?</summary>
                <dl>
                    <dt>VPIP</dt><dd>How many hands someone chooses to play. Higher means looser.</dd>
                    <dt>PFR</dt><dd>How often they raise before the flop. Higher means more aggressive.</dd>
                    <dt>Avg/hand</dt><dd>Dollars won or lost per hand dealt. Fairer than total profit for people who play less often.</dd>
                    <dt>Momentum</dt><dd>Avg/hand across their last 5 sessions. Green dots are winning nights; the arrow shows the direction of the trend.</dd>
                    <dt>Style tags</dt><dd>Shark (tight-aggressive), Maniac (loose-aggressive), Rock (tight-passive) and Calling Station (loose-passive), split at the group's median VPIP and PFR.</dd>
                    <dt>ATS</dt><dd>Attempt to steal: how often they open-raise from late position when everyone has folded to them.</dd>
                </dl>
            </details>
        </section>'''


def build_past_players_html(past_players: Optional[list], window_days: int) -> str:
    """Collapsed list of players outside the activity window (history kept)."""
    if not past_players:
        return ""
    rows = ""
    for p in past_players:
        cls = "positive" if p["profit"] >= 0 else "negative"
        pl_td = ('<td class="num"><span class="private-amt" title="Amount not shown">&mdash;</span></td>'
                 if p.get("private") else f'<td class="num {cls}">{money(p["profit"])}</td>')
        rows += f"""
                        <tr>
                            <td>{esc(p['name'])}</td>
                            <td class="num">{p['games']}</td>
                            <td class="num">{p['hands']:,}</td>
                            {pl_td}
                            <td class="num">{fmt_date(p['last_played_ms'])}</td>
                        </tr>"""
    n = len(past_players)
    who = "player hasn't" if n == 1 else "players haven't"
    return f'''
        <section class="past-players" id="past-players">
            <h2 class="section-title">Past Players</h2>
            <p class="section-lede">Their hands still count toward the session and hand totals; they're just off the leaderboard, profiles and charts until they sit back down.</p>
            <details>
                <summary><strong>{n} {who}</strong> played in the last {window_days} days. Show them.</summary>
                <div class="table-scroll">
                    <table>
                        <thead><tr><th scope="col">Player</th><th class="num" scope="col">Sessions</th><th class="num" scope="col">Hands</th><th class="num" scope="col">Lifetime profit/loss</th><th class="num" scope="col">Last played</th></tr></thead>
                        <tbody>{rows}
                        </tbody>
                    </table>
                </div>
            </details>
        </section>'''


def build_html(summary: dict, charts: dict, table_data: list,
               latest_session: dict = None, chart_data: dict = None,
               past_players: Optional[list] = None, records: Optional[dict] = None,
               now_ms: Optional[int] = None, private_names: Optional[set] = None,
               starting_hands: Optional[dict] = None) -> str:
    """Build the complete HTML dashboard as a string."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    now_ms = now_ms or int(now.timestamp() * 1000)

    # Interactive chart payload + renderer (inlined — page stays self-contained)
    chart_data_json = json.dumps(
        chart_data or {}, separators=(",", ":"), allow_nan=False,
    ).replace("</", "<\\/")
    chart_js = CHART_JS_PATH.read_text(encoding="utf-8")
    page_js = PAGE_JS_PATH.read_text(encoding="utf-8")
    page_css = PAGE_CSS_PATH.read_text(encoding="utf-8")

    profile_slugs = {slugify(r["name"]) for r in table_data}
    if private_names is None:
        private_names = {r["name"] for r in table_data if r.get("private")}
        private_names |= {p["name"] for p in (past_players or []) if p.get("private")}
    leaderboard_section = build_leaderboard_html(table_data, now_ms)
    if starting_hands is None:
        starting_hands = build_starting_hands(DB_PATH, [r["name"] for r in table_data])
    player_profiles_section = build_player_profiles_html(table_data, now_ms, starting_hands)
    past_section = build_past_players_html(past_players, ACTIVE_WINDOW_DAYS)

    # Build interactive chart sections (rendered client-side by static/charts.js)
    chart_sections = ""
    chart_configs = [
        ("chart-archetypes", "Player Archetypes",
         "Where everyone falls on the classic VPIP/PFR style map, split at the group medians. "
         "Bubble size shows hands played; green means lifetime winner, red means lifetime loser. "
         "Hover a bubble for full stats."),
        ("chart-hand-analysis", "Hand Analysis",
         "Distribution of winning hand types and action frequency across all sessions."),
        ("chart-session-trends", "Session Trends",
         "Top chart tracks cumulative profit/loss for the 3 biggest winners and 2 of the biggest losers. "
         "Bottom heatmap shows every player\u2019s profit/loss per session at a glance. "
         "Hover any point or cell for details."),
        ("chart-momentum", "Player Momentum",
         "Individual per-session profit/loss for each player. Green bars = winning sessions, "
         "red bars = losing sessions. \u2191/\u2193 arrows indicate recent trend direction."),
        ("chart-correlations", "Stat Correlations",
         "Pearson correlation matrix between all HUD stats and total profit. "
         "Green indicates positive correlation, red indicates negative."),
        ("chart-profit-drivers", "Profit Drivers",
         "Regression analysis showing which HUD stats most strongly predict profit. "
         "Each panel shows a scatter plot with best-fit line, R\u00b2, and p-value. "
         "Hover a point to see who it is."),
    ]
    for div_id, title, description in chart_configs:
        chart_sections += f"""
        <section class="chart-section" id="{div_id}-section">
            <h2 class="section-title">{title}</h2>
            <p class="chart-description">{description}</p>
            <div class="ichart" id="{div_id}"></div>
        </section>"""

    # Side-by-side architecture diagrams
    if "pipeline_diagram.png" in charts and "cicd_diagram.png" in charts:
        chart_sections += f"""
        <section class="chart-section" id="architecture">
            <h2 class="section-title">Architecture &amp; CI/CD</h2>
            <p class="chart-description">Left: how data flows from raw JSON files through the pipeline to this dashboard. Right: the CI/CD workflow that validates and deploys every change.</p>
            <div class="diagram-pair">
                <img src="data:image/png;base64,{charts['pipeline_diagram.png']}" alt="Pipeline Architecture" />
                <img src="data:image/png;base64,{charts['cicd_diagram.png']}" alt="CI/CD Workflow" />
            </div>
        </section>"""

    first_label = fmt_date(summary.get("first_hand_ms"), "%B %Y")
    active_count = len(table_data)
    past_link = ('<a class="navlink" href="#past-players">Past players</a>'
                 if past_players else "")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Home-game poker analytics: leaderboard, HUD stats, player profiles, and session trends. Auto-generated from PokerNow session logs.">
    <meta name="theme-color" content="#1a1a2e">
    <meta property="og:title" content="Poker Analytics Dashboard">
    <meta property="og:description" content="Leaderboard, HUD stats, and scouting reports for our home game.">
    <meta property="og:type" content="website">
    <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='0.9em' font-size='90' fill='%23e94560'%3E%E2%99%A0%3C/text%3E%3C/svg%3E">
    <title>Poker Analytics Dashboard</title>
    <style>
{page_css}
    </style>
</head>
<body>
    <nav class="topnav" aria-label="Sections">
        <div class="topnav-inner">
            <a class="brand" href="#top">&#9824; Home Game</a>
            <a class="navlink" href="#latest">Latest session</a>
            <a class="navlink" href="#leaderboard">Leaderboard</a>
            <a class="navlink" href="#profiles">Profiles</a>
            <a class="navlink" href="#chart-archetypes-section">Charts</a>
            {past_link}
        </div>
    </nav>
    <div class="container" id="top">
        <header class="masthead">
            <h1><span class="suit" aria-hidden="true">&#9824;</span>Poker Analytics Dashboard</h1>
            <p class="subtitle"><strong>{summary['total_games']} sessions</strong> and <strong>{summary['total_hands']:,} hands</strong> since {first_label}, with {summary['total_events']:,} actions tracked. The leaderboard, profiles and charts follow the <strong>{active_count} regulars</strong> who've played in the last 12 months.</p>
        </header>

        {build_latest_session_html(latest_session, profile_slugs, records, private_names)}

        {leaderboard_section}

        {player_profiles_section}

        <div class="charts-divider"></div>
        {chart_sections}

        {past_section}

        <footer>
            <p>Last updated: {timestamp}</p>
            <p>Built automatically by GitHub Actions from {summary['files_ingested']} session files</p>
        </footer>
    </div>

    <script>
{page_js}
    </script>
    <script>
    window.CHART_DATA = {chart_data_json};
    {chart_js}
    </script>
</body>
</html>"""

    return html


def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else OUTPUT_DIR
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("POKER DASHBOARD GENERATOR")
    print("=" * 50)

    # Step 1: Run full pipeline
    print("\n[1/4] Running data pipeline...")
    summary = run_pipeline(DB_PATH)
    print(f"  Ingested {summary['files_ingested']} files")
    print(f"  {summary['total_hands']} hands, {summary['total_players']} players")
    activity_info = get_activity(DB_PATH)
    active_names = activity_info["active_names"]
    private_names = activity_info["private_names"]
    past_players = get_past_players(activity_info)
    print(f"  {len(active_names)} players active in the last {ACTIVE_WINDOW_DAYS} days, "
          f"{len(past_players)} past players")

    # Step 2: Generate diagram PNGs + interactive chart data
    print("\n[2/4] Generating diagrams and chart data...")
    charts = generate_chart_base64(DB_PATH, output_dir)
    chart_data = build_chart_data(DB_PATH, min_games=MIN_GAMES, active_names=active_names,
                                  private_names=private_names)
    print(f"  Generated {len(charts)} diagrams + interactive chart payload")

    # Step 3: Get table data
    print("\n[3/4] Building player leaderboard...")
    table_data = get_table_data(DB_PATH, active_names)
    print(f"  {len(table_data)} players in leaderboard")

    # Step 4: Generate HTML
    print("\n[4/4] Generating HTML dashboard...")
    latest_session = get_latest_session_summary(DB_PATH)
    records = get_session_records(DB_PATH, active_names, exclude_names=private_names)
    html = build_html(summary, charts, table_data, latest_session, chart_data,
                      past_players=past_players, records=records,
                      now_ms=activity_info["now_ms"], private_names=private_names)

    output_path = Path(output_dir) / "index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = output_path.stat().st_size / 1024
    print(f"\n  Dashboard written to: {output_path}")
    print(f"  File size: {size_kb:.1f} KB")
    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()
