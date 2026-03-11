"""Auto-generated scouting reports for player profiles.

Analyzes HUD stats and produces 2-4 actionable advice bullets
describing how to exploit each player's tendencies.
"""


def generate_scouting_report(player: dict) -> list[str]:
    """Generate 2-4 actionable advice bullets for exploiting a player.

    Args:
        player: Dict with stat keys from get_table_data().
                Stats may be None for nullable fields.

    Returns:
        List of 2-4 advice strings, sorted by priority (most impactful first).
    """
    rules = _get_rules()
    applicable = []

    for _category, condition_fn, priority, template in rules:
        try:
            if condition_fn(player):
                applicable.append((priority, template))
        except (TypeError, KeyError):
            continue

    applicable.sort(key=lambda x: x[0], reverse=True)
    bullets = [_format_advice(t, player) for _, t in applicable[:4]]

    if len(bullets) < 2:
        bullets.extend(_fallback_advice(player, existing=len(bullets)))

    return bullets[:4]


def _get_rules():
    """Return all scouting rules: (category, condition_fn, priority, advice_template)."""
    return [
        # ── PREFLOP TENDENCIES ──────────────────────────────────────

        ("preflop", lambda p: p["conv_vpip_pct"] > 40,
         9,
         "Plays too many hands preflop (VPIP {conv_vpip_pct:.0f}%). "
         "Tighten your opening range and value-bet relentlessly — "
         "they'll call with worse."),

        ("preflop", lambda p: p["conv_vpip_pct"] < 20,
         7,
         "Extremely tight preflop (VPIP {conv_vpip_pct:.0f}%). "
         "Steal their blinds aggressively and fold to their raises "
         "unless you have a premium hand."),

        ("preflop", lambda p: p["conv_vpip_pct"] > 30 and p["pfr_pct"] < 10,
         8,
         "Limps excessively (VPIP {conv_vpip_pct:.0f}%, PFR {pfr_pct:.0f}%). "
         "Iso-raise their limps with a wide range to play heads-up "
         "in position against a weak, capped range."),

        ("preflop", lambda p: p["pfr_pct"] > 20,
         6,
         "Raises preflop often (PFR {pfr_pct:.0f}%). "
         "Widen your 3-bet range against them, especially in position, "
         "and be prepared to call lighter preflop."),

        ("preflop",
         lambda p: p.get("three_bet_pct") is not None and p["three_bet_pct"] < 5,
         5,
         "Rarely 3-bets ({three_bet_pct:.0f}%). "
         "You can open-raise liberally when they're behind you — "
         "they almost never fight back preflop."),

        ("preflop",
         lambda p: p.get("three_bet_pct") is not None and p["three_bet_pct"] > 10,
         6,
         "Aggressive 3-bettor ({three_bet_pct:.0f}%). "
         "Include more 4-bet bluffs in your range and trap with "
         "premium hands by flatting their 3-bets."),

        # ── BIG BLIND PLAY ──────────────────────────────────────────

        ("bb_play",
         lambda p: p.get("bb_fold_to_steal_pct") is not None and p["bb_fold_to_steal_pct"] > 50,
         8,
         "Folds the big blind to steals {bb_fold_to_steal_pct:.0f}% of the time. "
         "Attack their blind from late position with a very wide range."),

        ("bb_play",
         lambda p: p.get("bb_defend_pct") is not None and p["bb_defend_pct"] > 60,
         6,
         "Defends their big blind too widely ({bb_defend_pct:.0f}%). "
         "Value-bet thinly when they call your steal — "
         "they're defending with many weak hands."),

        ("bb_play",
         lambda p: p.get("bb_defend_pct") is not None and p["bb_defend_pct"] < 40,
         7,
         "Rarely defends the big blind ({bb_defend_pct:.0f}%). "
         "Raise any two cards from the button and cutoff "
         "when they're in the BB."),

        # ── STEAL GAME ──────────────────────────────────────────────

        ("steal",
         lambda p: p.get("ats_pct") is not None and p["ats_pct"] > 40,
         6,
         "Steals aggressively from late position (ATS {ats_pct:.0f}%). "
         "3-bet them light from the blinds to fight back, "
         "and don't give up your blinds easily."),

        ("steal",
         lambda p: p.get("ats_pct") is not None and p["ats_pct"] < 25,
         4,
         "Rarely attempts steals (ATS {ats_pct:.0f}%). "
         "When they do raise from late position, give their range "
         "more credit — they likely have a real hand."),

        # ── POSTFLOP PLAY ───────────────────────────────────────────

        ("postflop",
         lambda p: p.get("aggression_factor") is not None and p["aggression_factor"] < 1.5,
         8,
         "Passive postflop (AF {aggression_factor:.1f}). "
         "When they bet or raise, respect it — it usually means "
         "a strong hand. Bluff them more since they rarely fight back."),

        ("postflop",
         lambda p: p.get("aggression_factor") is not None and p["aggression_factor"] > 3.5,
         7,
         "Hyper-aggressive postflop (AF {aggression_factor:.1f}). "
         "Call down lighter with medium-strength hands and let them "
         "bluff into you. Avoid folding to single bets."),

        ("postflop",
         lambda p: p.get("cbet_pct") is not None and p["cbet_pct"] > 70,
         7,
         "C-bets relentlessly ({cbet_pct:.0f}%). "
         "Float their flop bets with position and attack when they "
         "check the turn — their range is often air."),

        ("postflop",
         lambda p: p.get("cbet_pct") is not None and p["cbet_pct"] < 50,
         5,
         "Rarely continuation bets ({cbet_pct:.0f}%). "
         "When they do c-bet, their range is strong. "
         "Stab at pots when they check after raising preflop."),

        ("postflop",
         lambda p: p.get("fold_to_cbet_pct") is not None and p["fold_to_cbet_pct"] > 55,
         8,
         "Folds to c-bets {fold_to_cbet_pct:.0f}% of the time. "
         "C-bet aggressively against them, even with air — "
         "they give up too easily on the flop."),

        ("postflop",
         lambda p: p.get("fold_to_cbet_pct") is not None and p["fold_to_cbet_pct"] < 30,
         5,
         "Rarely folds to c-bets ({fold_to_cbet_pct:.0f}%). "
         "Only c-bet for value against them. "
         "Save your bluffs for the turn and river."),

        # ── SHOWDOWN TENDENCIES ─────────────────────────────────────

        ("showdown",
         lambda p: p.get("wtsd_pct") is not None and p["wtsd_pct"] > 35,
         7,
         "Goes to showdown too often (WTSD {wtsd_pct:.0f}%). "
         "This is a calling station — never bluff them on the river. "
         "Value-bet thinner than normal."),

        ("showdown",
         lambda p: p.get("wtsd_pct") is not None and p["wtsd_pct"] < 20,
         6,
         "Avoids showdowns (WTSD {wtsd_pct:.0f}%). "
         "Apply pressure with bets on later streets — "
         "they fold too much when facing aggression."),

        ("showdown",
         lambda p: p.get("wsd_pct") is not None and p["wsd_pct"] < 45,
         5,
         "Loses at showdown frequently (W$SD {wsd_pct:.0f}%). "
         "They're reaching showdown with weak holdings. "
         "Value-bet for maximum extraction."),

        ("showdown",
         lambda p: p.get("wsd_pct") is not None and p["wsd_pct"] > 55,
         4,
         "Wins at showdown often (W$SD {wsd_pct:.0f}%). "
         "They're selective about going to showdown. "
         "Don't try to bluff them off a hand at the river."),
    ]


def _fallback_advice(player: dict, existing: int) -> list[str]:
    """Generate generic advice when fewer than 2 specific rules apply."""
    fallbacks = []
    vpip = player.get("conv_vpip_pct", 30)
    if 20 <= vpip <= 40:
        fallbacks.append(
            "Plays a standard preflop range (VPIP {conv_vpip_pct:.0f}%). "
            "Focus on positional advantage and hand reading to find edges."
        )
    if len(fallbacks) + existing < 2:
        fallbacks.append(
            "No strong exploitable tendencies detected. "
            "Play solid fundamental poker and look for live reads at the table."
        )
    needed = 2 - existing
    return [_format_advice(f, player) for f in fallbacks[:needed]]


def _format_advice(template: str, player: dict) -> str:
    """Format an advice template with player stat values."""
    safe = {k: (v if v is not None else 0) for k, v in player.items()}
    return template.format(**safe)
