"""Personal improvement advice for player profiles.

Where scouting.py tells *opponents* how to exploit a player, this module
speaks to the player: which of their tendencies cost them the most, why,
and one concrete thing to try next session, plus what they already do well.

How leaks are ranked
--------------------
Each stat has a healthy target band for a short-handed home game. A stat
outside its band is a leak, scored by how far outside it is (in band widths)
times how much the stat matters, with a bonus when the player is also worse
than the table median in the same direction. That keeps the advice personal
in a game where most of the table shares the same tendencies. Only one leak
per area of the game (preflop, blinds, postflop, showdown) is shown, and a
stat needs MIN_SAMPLE opportunities before any advice is based on it.
"""
from statistics import median
from typing import Optional

MIN_SAMPLE = 20      # opportunities needed before judging a stat
MAX_LEAKS = 3
MAX_STRENGTHS = 2

# key: (label, area, low, high, weight, gauge_max, sample_key)
#   low/high: healthy target band; gauge_max: right edge of the gauge
TARGETS = {
    "conv_vpip_pct":        ("Hands played (VPIP)", "preflop", 22, 35, 1.3, 100, "hands"),
    "pfr_pct":              ("Preflop raise (PFR)", "preflop", 12, 25, 1.2, 50, "hands"),
    "three_bet_pct":        ("3-bet", "preflop", 5, 10, 0.8, 25, "three_bet_opportunities"),
    "flop_seen_pct":        ("Flops seen", "preflop", 25, 45, 0.7, 100, "flop_eligible_hands"),
    "bb_defend_pct":        ("Big blind defense", "blinds", 35, 60, 0.7, 100, "bb_faced_raise_hands"),
    "bb_fold_to_steal_pct": ("Big blind fold to steal", "blinds", 35, 60, 0.6, 100, "bb_steal_faced_hands"),
    "ats_pct":              ("Steal attempts (ATS)", "blinds", 25, 45, 0.7, 100, "ats_opportunities"),
    "aggression_factor":    ("Postflop aggression (AF)", "postflop", 1.5, 3.5, 1.2, 5, "postflop_actions"),
    "cbet_pct":             ("Continuation bet", "postflop", 50, 75, 0.9, 100, "cbet_opportunities"),
    "fold_to_cbet_pct":     ("Fold to c-bet", "postflop", 35, 55, 0.8, 100, "faced_cbet"),
    "wtsd_pct":             ("Went to showdown (WTSD)", "showdown", 24, 33, 0.9, 60, "flop_seen_hands"),
    "wsd_pct":              ("Won at showdown (W$SD)", "showdown", 50, 100, 1.0, 100, "showdown_hands"),
}

# (key, direction) -> (title, why it costs you, try this next session)
LEAK_TEXT = {
    ("conv_vpip_pct", "high"): (
        "Play fewer hands",
        "You put money in {v:.0f}% of the time. Weak starting hands like "
        "offsuit connectors and small aces keep making second-best pairs, "
        "which are the most expensive hands in poker.",
        "Next session, fold anything offsuit below A-T or K-J unless you're on "
        "the button or can see the flop for one bet in a big multiway pot."),
    ("conv_vpip_pct", "low"): (
        "Open up a little",
        "At {v:.0f}% you're folding hands that win money in a game this loose, "
        "and the table can read your raises as monsters.",
        "Add suited connectors and any pocket pair from the cutoff and button."),
    ("pfr_pct", "low"): (
        "Raise instead of limping",
        "You raise preflop only {v:.0f}% of the time. Limping lets five people "
        "see the flop, so even good hands rarely win, and you never pick up the "
        "pot uncontested.",
        "Make a rule: if a hand is good enough to play, raise it to about 4x "
        "the big blind plus 1x for each limper. Fold the ones that aren't."),
    ("pfr_pct", "high"): (
        "Pick better spots to raise",
        "Raising {v:.0f}% of hands is more than this table respects, so your "
        "raises get called by hands that crush your bluffs.",
        "Keep raising for value, but drop the weakest third of your raising "
        "hands from early position."),
    ("three_bet_pct", "low"): (
        "Re-raise your best hands",
        "You 3-bet only {v:.0f}% of the time. Calling raises with premium "
        "hands lets weaker hands in cheap and hides nothing.",
        "Always re-raise QQ+, AK, and add AQ suited on the button against "
        "late-position raisers."),
    ("three_bet_pct", "high"): (
        "Ease off the re-raises",
        "At {v:.0f}% your 3-bets are wide enough that callers are ahead of "
        "your range often.",
        "Cut 3-bet bluffs from out of position; keep them for the button."),
    ("flop_seen_pct", "high"): (
        "See fewer flops",
        "You see {v:.0f}% of flops. Each extra flop with a marginal hand is "
        "a small leak that adds up over hundreds of hands.",
        "Before calling preflop, ask: what flop am I hoping for, and will I "
        "know where I stand when I hit it?"),
    ("bb_defend_pct", "high"): (
        "Defend your big blind less",
        "You call {v:.0f}% of raises in the big blind. Playing out of "
        "position with weak hands loses more than the blind you save.",
        "Fold offsuit hands below K-T and small offsuit aces to early-position "
        "raises."),
    ("bb_defend_pct", "low"): (
        "Defend your big blind more",
        "Folding the big blind {v_inv:.0f}% of the time hands free money to "
        "anyone who raises.",
        "Against button and cutoff raises, call with any suited hand and any "
        "two cards ten or higher."),
    ("bb_fold_to_steal_pct", "high"): (
        "Stop giving up your blind",
        "You fold to {v:.0f}% of late-position steals, so the late seats can "
        "raise you with anything and profit.",
        "Re-raise a few hands like A-x suited and pocket pairs against "
        "button steals."),
    ("ats_pct", "low"): (
        "Steal the blinds more",
        "You attempt to steal only {v:.0f}% of the time when it's folded to "
        "you in late position. Those are the easiest pots at the table.",
        "When it folds to you on the button, raise any ace, any pair, any "
        "two face cards, and suited connectors."),
    ("ats_pct", "high"): (
        "Steal a little less",
        "At {v:.0f}% the blinds have caught on and fight back.",
        "Keep stealing with hands that play well when called; drop the junk."),
    ("aggression_factor", "low"): (
        "Bet more, call less",
        "After the flop you call much more than you bet or raise (AF {v:.1f}). "
        "Calling only wins at showdown; betting can also win when everyone "
        "folds.",
        "When you hit top pair or better, bet it. When you'd call a bet "
        "with a draw in position, try raising instead now and then."),
    ("aggression_factor", "high"): (
        "Slow down postflop",
        "AF {v:.1f} means you bet and raise far more than you call, so "
        "observant players will call you down light.",
        "Check back more medium-strength hands on the turn."),
    ("cbet_pct", "low"): (
        "Follow up your preflop raises",
        "You continuation-bet only {v:.0f}% of the time after raising "
        "preflop, which gives away the initiative you paid for.",
        "Bet about half the pot on dry flops (like K-7-2) heads-up, whether "
        "you hit or not."),
    ("cbet_pct", "high"): (
        "Check some flops back",
        "C-betting {v:.0f}% of flops is easy to exploit by floating.",
        "Check back on wet, connected boards when you missed and have "
        "several opponents."),
    ("fold_to_cbet_pct", "high"): (
        "Don't give up so fast",
        "You fold to {v:.0f}% of continuation bets. Raisers bet most flops "
        "whether they hit or not, so you're folding the best hand often.",
        "Call one flop bet with any pair or draw when you're heads-up."),
    ("fold_to_cbet_pct", "low"): (
        "Let some flops go",
        "Calling {v_inv:.0f}% of c-bets means paying off when the raiser "
        "really has it.",
        "Fold no-pair, no-draw hands to flop bets in multiway pots."),
    ("wtsd_pct", "high"): (
        "Fold more on the river",
        "You go to showdown in {v:.0f}% of hands where you see a flop. Plenty "
        "of those are calls with hands that can only beat a bluff, and this "
        "table rarely bluffs.",
        "On the river, ask what worse hand they'd bet. If you can't name one, "
        "fold."),
    ("wtsd_pct", "low"): (
        "Call down a little more",
        "Reaching showdown only {v:.0f}% of the time can mean folding the "
        "best hand to pressure.",
        "Call one more street with top pair when the board doesn't change."),
    ("wsd_pct", "low"): (
        "Get to showdown with stronger hands",
        "You win only {v:.0f}% of showdowns, so you're often calling with "
        "the second-best hand at the end.",
        "Go to showdown with fewer marginal hands. Middle pair and worse are "
        "usually beat on the river in a multiway pot."),
}

STRENGTH_TEXT = {
    "conv_vpip_pct": "Good hand selection: you play a healthy {v:.0f}% of hands.",
    "pfr_pct": "Solid preflop aggression: you raise {v:.0f}% of hands.",
    "three_bet_pct": "Well-balanced 3-betting at {v:.0f}%.",
    "flop_seen_pct": "Disciplined about which flops you see ({v:.0f}%).",
    "bb_defend_pct": "Smart big blind defense ({v:.0f}%).",
    "bb_fold_to_steal_pct": "You don't let late-position players steal your blind for free.",
    "ats_pct": "You take the free money: {v:.0f}% steal attempts from late position.",
    "aggression_factor": "Healthy postflop aggression (AF {v:.1f}).",
    "cbet_pct": "Good follow-through: you c-bet {v:.0f}% after raising.",
    "fold_to_cbet_pct": "You don't fold too easily to continuation bets.",
    "wtsd_pct": "Good river discipline: you go to showdown {v:.0f}% of the time.",
    "wsd_pct": "When you go to showdown, you usually have it: {v:.0f}% won.",
}


def table_medians(players: list) -> dict:
    """Median of each target stat across the given players (None if no data)."""
    out = {}
    for key in TARGETS:
        vals = [p[key] for p in players if p.get(key) is not None]
        out[key] = round(median(vals), 1) if vals else None
    return out


def _fmt(key: str, v: float) -> str:
    return f"{v:.1f}" if key == "aggression_factor" else f"{v:.0f}%"


def _enough(player: dict, key: str) -> bool:
    sample_key = TARGETS[key][6]
    samples = player.get("samples") or {}
    n = samples.get(sample_key)
    return n is None or n >= MIN_SAMPLE  # unknown sample: trust the stat


def generate_coaching(player: dict, medians: dict) -> dict:
    """Build improvement advice for one player.

    Returns {"headline": str, "leaks": [...], "strengths": [...]} where each
    leak is {"key", "title", "why", "try", "label", "value", "value_label",
    "low", "high", "median", "gauge_max"} and strengths are strings.
    """
    candidates = []
    in_band = []
    for key, (label, area, low, high, weight, gmax, _s) in TARGETS.items():
        v = player.get(key)
        if v is None or not _enough(player, key):
            continue
        width = high - low
        if v > high and (key, "high") in LEAK_TEXT:
            direction, dist = "high", (v - high) / width
        elif v < low and (key, "low") in LEAK_TEXT:
            direction, dist = "low", (low - v) / width
        else:
            if low <= v <= high:
                in_band.append((weight, key, v))
            continue
        score = dist * weight
        med = medians.get(key)
        if med is not None and ((direction == "high" and v > med) or
                                (direction == "low" and v < med)):
            score *= 1.5  # worse than the table too: more personal
        candidates.append((score, key, direction, area, v))

    candidates.sort(reverse=True)
    leaks, used_areas = [], set()
    for score, key, direction, area, v in candidates:
        if area in used_areas:
            continue
        used_areas.add(area)
        label, _a, low, high, _w, gmax, _s = TARGETS[key]
        title, why, tip = LEAK_TEXT[(key, direction)]
        fmt = {"v": v, "v_inv": 100 - v}
        leaks.append({
            "key": key, "title": title,
            "why": why.format(**fmt), "try": tip.format(**fmt),
            "label": label, "value": round(v, 1), "value_label": _fmt(key, v),
            "low": low, "high": high, "median": medians.get(key),
            "gauge_max": gmax,
        })
        if len(leaks) == MAX_LEAKS:
            break

    in_band.sort(reverse=True)
    strengths = [STRENGTH_TEXT[key].format(v=v) for _w, key, v in in_band[:MAX_STRENGTHS]]

    return {"headline": _headline(player), "leaks": leaks, "strengths": strengths}


def _headline(player: dict) -> str:
    """One-sentence read on results and recent direction."""
    hands = player.get("hands_played", 0)
    avg = player.get("avg_profit", 0) or 0
    momentum = player.get("momentum") or []

    if player.get("private"):
        # Lifetime loss is large enough that amounts are hidden on the board
        result = f"Your results over {hands:,} hands are below break-even"
    elif avg > 0.05:
        result = f"You're winning about ${avg:.2f} a hand over {hands:,} hands"
    elif avg < -0.05:
        result = f"You're losing about ${abs(avg):.2f} a hand over {hands:,} hands"
    else:
        result = f"You're close to break-even over {hands:,} hands"

    trend = ""
    if len(momentum) >= 3:
        delta = momentum[-1] - momentum[0]
        if delta > 0.1:
            trend = ", and your last few sessions are trending up"
        elif delta < -0.1:
            trend = ", but your last few sessions are trending down"

    note = ""
    if hands < 400:
        note = " That's still a small sample, so treat these as early reads."
    return result + trend + "." + note


def coaching_gauge_pct(value: float, gauge_max: float) -> float:
    """Position on a 0-100% gauge track, clamped."""
    if gauge_max <= 0:
        return 0.0
    return max(0.0, min(100.0, value / gauge_max * 100))


def leak_gauge(leak: dict) -> dict:
    """Gauge positions (percent of track) for the leak's value, band and median."""
    g = leak["gauge_max"]
    med: Optional[float] = leak.get("median")
    return {
        "you": coaching_gauge_pct(leak["value"], g),
        "band_left": coaching_gauge_pct(leak["low"], g),
        "band_right": coaching_gauge_pct(leak["high"], g),
        "median": coaching_gauge_pct(med, g) if med is not None else None,
    }
