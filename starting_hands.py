"""Starting-hand analysis for player profiles.

Answers "does this player play good starting hands, and fold bad ones?"
from the hole cards the replays reveal:
  * every hand of the account that downloaded the replay,
  * showdowns,
  * hands people chose to show (after winning uncontested, or after folding).

Revealed cards are a biased sample for most players: we mostly see played
hands that reached showdown, and only the folds people *chose* to show.
So each player gets a coverage figure, and fold-based metrics only appear
when enough of their folds are visible (FULL_FOLD_COVERAGE).

Hand strength = all-in equity vs. one random hand (HAND_EQUITY below),
precomputed once with a seeded 40,000-trial Monte Carlo per hand using the
eval7 evaluator. It isn't a perfect multiway ranking (suited connectors
play better than their equity suggests), but it's a fair, objective scale.
"""
from collections import defaultdict

from database import get_connection

RANKS = "AKQJT98765432"

# Equity (%) of each starting hand all-in preflop vs. one random hand
HAND_EQUITY = {
    "AA": 85.3, "AKs": 67.3, "AQs": 66.6, "AJs": 65.5, "ATs": 64.9, "A9s": 62.9, "A8s": 62.0, "A7s": 60.7, "A6s": 59.6, "A5s": 60.2, "A4s": 59.1, "A3s": 58.2, "A2s": 57.4, "AKo": 65.5, "AQo": 64.6, "AJo": 63.7, "ATo": 62.7, "A9o": 60.4, "A8o": 59.7, "A7o": 58.6, "A6o": 57.8, "A5o": 57.8, "A4o": 56.6, "A3o": 55.8, "A2o": 54.8,
    "KK": 82.7, "KQs": 63.1, "KJs": 62.4, "KTs": 61.9, "K9s": 60.0, "K8s": 58.5, "K7s": 57.9, "K6s": 56.5, "K5s": 55.6, "K4s": 55.1, "K3s": 54.4, "K2s": 53.3, "KQo": 61.2, "KJo": 60.4, "KTo": 60.1, "K9o": 58.2, "K8o": 55.8, "K7o": 55.4, "K6o": 54.1, "K5o": 53.3, "K4o": 52.5, "K3o": 51.1, "K2o": 50.5,
    "QQ": 80.3, "QJs": 60.0, "QTs": 59.7, "Q9s": 57.5, "Q8s": 56.1, "Q7s": 54.1, "Q6s": 53.6, "Q5s": 52.8, "Q4s": 52.0, "Q3s": 51.2, "Q2s": 50.4, "QJo": 57.8, "QTo": 56.7, "Q9o": 54.9, "Q8o": 53.8, "Q7o": 52.1, "Q6o": 50.7, "Q5o": 50.2, "Q4o": 49.3, "Q3o": 48.4, "Q2o": 46.8,
    "JJ": 77.6, "JTs": 57.3, "J9s": 55.7, "J8s": 54.1, "J7s": 52.0, "J6s": 50.5, "J5s": 50.1, "J4s": 49.0, "J3s": 48.6, "J2s": 47.6, "JTo": 55.3, "J9o": 53.2, "J8o": 51.5, "J7o": 50.0, "J6o": 48.0, "J5o": 47.3, "J4o": 46.0, "J3o": 45.2, "J2o": 44.6,
    "TT": 74.9, "T9s": 54.3, "T8s": 52.1, "T7s": 50.8, "T6s": 49.2, "T5s": 47.3, "T4s": 46.2, "T3s": 45.8, "T2s": 45.3, "T9o": 51.2, "T8o": 49.9, "T7o": 48.1, "T6o": 46.1, "T5o": 44.1, "T4o": 43.0, "T3o": 42.6, "T2o": 41.5,
    "99": 72.1, "98s": 51.1, "97s": 49.5, "96s": 47.3, "95s": 45.6, "94s": 44.0, "93s": 43.2, "92s": 42.5, "98o": 48.1, "97o": 45.9, "96o": 44.5, "95o": 42.4, "94o": 40.8, "93o": 40.0, "92o": 39.3,
    "88": 69.3, "87s": 47.9, "86s": 46.0, "85s": 44.1, "84s": 42.5, "83s": 40.9, "82s": 40.4, "87o": 44.9, "86o": 43.2, "85o": 41.3, "84o": 39.2, "83o": 37.1, "82o": 36.4,
    "77": 66.8, "76s": 45.9, "75s": 43.4, "74s": 41.6, "73s": 40.2, "72s": 37.9, "76o": 42.4, "75o": 40.4, "74o": 38.4, "73o": 36.7, "72o": 34.4,
    "66": 63.5, "65s": 42.8, "64s": 41.4, "63s": 40.0, "62s": 37.7, "65o": 39.6, "64o": 38.1, "63o": 35.8, "62o": 34.1,
    "55": 60.1, "54s": 41.2, "53s": 39.4, "52s": 37.6, "54o": 37.5, "53o": 36.6, "52o": 34.4,
    "44": 57.5, "43s": 38.8, "42s": 36.7, "43o": 34.7, "42o": 33.1,
    "33": 53.7, "32s": 35.9, "32o": 32.5,
    "22": 49.9,
}

# Thresholds for the panel
MIN_SEEN_PLAYED = 15        # seen played hands needed to show anything
FULL_FOLD_COVERAGE = 0.5    # share of folds visible before judging folding
MIN_SEEN_FOLDED = 30
TOP_PCT = 20                # "strong" = top 20% of dealt hands
JUNK_PCT = 50               # "weak" = bottom half of dealt hands


def _combos(key: str) -> int:
    if len(key) == 2:
        return 6
    return 4 if key.endswith("s") else 12


def _build_percentiles() -> dict:
    """Top-X% of all dealt hands each starting hand falls in (combo-weighted).

    e.g. AA -> 0.5 (top 0.5%), 72o -> ~100. Uses the midpoint of the hand's
    own combos so ties land fairly.
    """
    order = sorted(HAND_EQUITY, key=lambda k: -HAND_EQUITY[k])
    total = sum(_combos(k) for k in order)  # 1326
    out, running = {}, 0
    for k in order:
        c = _combos(k)
        out[k] = round((running + c / 2) / total * 100, 1)
        running += c
    return out


HAND_PERCENTILE = _build_percentiles()


def hand_key(card1: str, card2: str):
    """('Kd', 'As') -> 'AKo'; returns None for missing/invalid cards."""
    if not card1 or not card2 or len(card1) < 2 or len(card2) < 2:
        return None
    r1, s1, r2, s2 = card1[0].upper(), card1[1], card2[0].upper(), card2[1]
    if r1 not in RANKS or r2 not in RANKS:
        return None
    if r1 == r2:
        return r1 + r2
    hi, lo = sorted((r1, r2), key=RANKS.index)
    return hi + lo + ("s" if s1 == s2 else "o")


def grid_keys():
    """13x13 grid keys row by row: pairs on the diagonal, suited above it."""
    rows = []
    for i, a in enumerate(RANKS):
        row = []
        for j, b in enumerate(RANKS):
            if i == j:
                row.append(a + b)
            elif i < j:
                row.append(a + b + "s")
            else:
                row.append(b + a + "o")
        rows.append(row)
    return rows


def get_preflop_decisions(db_path: str) -> dict:
    """Per canonical player: list of (decision, hand_key or None, showdown).

    decision is "played" (voluntarily called, raised or went all-in
    preflop) or "folded" (folded preflop without putting money in).
    Free big-blind checks and walks are neither and are skipped.
    showdown is True when the hand reached a showdown, this player never
    folded, and they turned their cards face up (a SHOW_CARDS event).
    Requiring the show event treats every player alike: the replay owner's
    cards are always in the file, but a hand they mucked at showdown is
    left out just as it is for everyone else.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    # Preflop = events before the first COMMUNITY_CARDS (type 9) in each hand
    cur.execute("""
        SELECT e.hand_id, e.seat, e.event_type
        FROM events e
        LEFT JOIN (
            SELECT hand_id, MIN(id) AS flop_id FROM events
            WHERE event_type = 9 GROUP BY hand_id
        ) f ON f.hand_id = e.hand_id
        WHERE e.event_type IN (7, 8, 11, 16)
          AND (f.flop_id IS NULL OR e.id < f.flop_id)
    """)
    voluntary, folded = defaultdict(set), defaultdict(set)
    rows = cur.fetchall()
    cur.execute("SELECT hand_id, seat, event_type FROM events WHERE event_type IN (11, 12, 15)")
    showdown_hands, folded_any, showed = set(), defaultdict(set), defaultdict(set)
    for r in cur.fetchall():
        if r["event_type"] == 15:
            showdown_hands.add(r["hand_id"])
        elif r["event_type"] == 12:
            showed[r["hand_id"]].add(r["seat"])
        else:
            folded_any[r["hand_id"]].add(r["seat"])
    for r in rows:
        if r["event_type"] == 11:
            folded[r["hand_id"]].add(r["seat"])
        else:
            voluntary[r["hand_id"]].add(r["seat"])

    cur.execute("""
        SELECT hand_id, seat, name, hole_card_1, hole_card_2
        FROM v_hand_players
    """)
    out = defaultdict(list)
    for r in cur.fetchall():
        hid, seat = r["hand_id"], r["seat"]
        if seat in voluntary.get(hid, ()):
            decision = "played"     # put money in, even if they folded later
        elif seat in folded.get(hid, ()):
            decision = "folded"
        else:
            continue
        at_showdown = (decision == "played" and hid in showdown_hands
                       and seat not in folded_any.get(hid, ())
                       and seat in showed.get(hid, ()))
        out[r["name"]].append((decision, hand_key(r["hole_card_1"], r["hole_card_2"]),
                               at_showdown))
    conn.close()
    return dict(out)


def summarize_player(decisions: list) -> dict:
    """Coverage, grid counts and strength metrics for one player."""
    played = [k for d, k, _sd in decisions if d == "played"]
    folded = [k for d, k, _sd in decisions if d == "folded"]
    showdown = [k for d, k, sd in decisions if sd and k]
    seen_played = [k for k in played if k]
    seen_folded = [k for k in folded if k]

    cells = defaultdict(lambda: {"played": 0, "folded": 0})
    for k in seen_played:
        cells[k]["played"] += 1
    for k in seen_folded:
        cells[k]["folded"] += 1

    played_cov = len(seen_played) / len(played) if played else 0.0
    folded_cov = len(seen_folded) / len(folded) if folded else 0.0
    full = folded_cov >= FULL_FOLD_COVERAGE and len(seen_folded) >= MIN_SEEN_FOLDED

    s = {
        "played_total": len(played), "folded_total": len(folded),
        "seen_played": len(seen_played), "seen_folded": len(seen_folded),
        "played_coverage": round(played_cov * 100),
        "folded_coverage": round(folded_cov * 100),
        "enough": len(seen_played) >= MIN_SEEN_PLAYED,
        "full": full,
        "cells": {k: dict(v) for k, v in cells.items()},
        "showdown_seen": len(showdown),
        "showdown_avg_pct": (round(sum(HAND_PERCENTILE[k] for k in showdown) / len(showdown))
                             if len(showdown) >= MIN_SEEN_PLAYED else None),
        "avg_played_pct": None, "strong_share": None, "weak_share": None,
        "weak_fold_rate": None, "strong_play_rate": None,
    }
    if seen_played:
        pcts = [HAND_PERCENTILE[k] for k in seen_played]
        s["avg_played_pct"] = round(sum(pcts) / len(pcts))
        s["strong_share"] = round(sum(p <= TOP_PCT for p in pcts) / len(pcts) * 100)
        s["weak_share"] = round(sum(p > JUNK_PCT for p in pcts) / len(pcts) * 100)
    if full:
        weak = [(d, k) for d, k, _sd in decisions if k and HAND_PERCENTILE[k] > JUNK_PCT]
        strong = [(d, k) for d, k, _sd in decisions if k and HAND_PERCENTILE[k] <= TOP_PCT]
        if weak:
            s["weak_fold_rate"] = round(sum(d == "folded" for d, _ in weak) / len(weak) * 100)
        if strong:
            s["strong_play_rate"] = round(sum(d == "played" for d, _ in strong) / len(strong) * 100)
    return s


def build_starting_hands(db_path: str, names) -> dict:
    """{name: summary} for the given players, plus "_table" with the median
    showdown-hand strength (the only figure comparable across players)."""
    from statistics import median
    decisions = get_preflop_decisions(db_path)
    out = {n: summarize_player(decisions.get(n, [])) for n in names}
    vals = [s["showdown_avg_pct"] for s in out.values() if s["showdown_avg_pct"] is not None]
    out["_table"] = {"showdown_avg_pct": round(median(vals)) if vals else None}
    return out
