"""
HUD statistics calculator for poker hand history data.

Calculates standard poker HUD stats:
- VPIP% (Voluntarily Put In Pot)
- PFR% (Pre-Flop Raise)
- ATS% (Attempt to Steal)
- Flop Seen % (saw the flop without folding preflop)
- BB Defense % (BB called/raised vs a preflop raise)
- BB Fold to Steal % (BB folded to a steal-position raise)
- 3-Bet % (re-raised after an initial preflop open raise)

These are computed from the events table by analysing preflop actions
for each hand.
"""
from collections import defaultdict
from database import get_connection, EVENT_TYPES


# Reverse map: name -> int
_ET = {v: k for k, v in EVENT_TYPES.items()}

# PokerNow event encoding (differs from standard poker terminology):
#   BET  (type 8)  = actual raise / re-raise to a new level
#   RAISE(type 7)  = call / limp (matching the current bet)
#   CHECK_CALL(0)  = check only (BB checking unraised pot preflop)
#   ALL_IN(type 16)= all-in (always follows a BET from same player preflop)
#
# Therefore:
#   VPIP  = had RAISE(7), BET(8), or ALL_IN(16) on ANY street
#           (PokerNow counts voluntary money across the whole hand,
#            so BB checking preflop but betting/calling postflop = VPIP)
#   PFR   = had BET(8) preflop (the only true raise action)
#   ATS   = had BET(8) from steal position in unopened pot

_VPIP_TYPES = {_ET["RAISE"], _ET["BET"], _ET["ALL_IN"]}  # any voluntary preflop action
_PFR_TYPES = {_ET["BET"]}                                  # actual raises only
_BLIND_TYPES = {_ET["SMALL_BLIND"], _ET["BIG_BLIND"]}
_COMMUNITY = _ET["COMMUNITY_CARDS"]
_FOLD = _ET["FOLD"]
_SB_TYPE = _ET["SMALL_BLIND"]
_BB_TYPE = _ET["BIG_BLIND"]


def _seats_clockwise(active_seats: list[int], dealer_seat: int) -> list[int]:
    """Return active seats in clockwise order starting AFTER the dealer.

    Poker preflop action order: UTG … CO, BTN, SB, BB.
    We sort seats so that the first seat after the BB acts first preflop
    and the BB acts last.
    """
    seats = sorted(active_seats)
    if not seats:
        return []
    # Rotate so dealer is first, then seats proceed clockwise
    idx = 0
    for i, s in enumerate(seats):
        if s > dealer_seat:
            idx = i
            break
    else:
        idx = 0  # wrap around
    return seats[idx:] + seats[:idx]


def _get_cutoff_seat(active_seats: list[int], dealer_seat: int) -> int | None:
    """Find the cutoff seat (one seat to the right of the button).

    In clockwise seat order, CO is the seat immediately before the dealer.
    """
    seats = sorted(active_seats)
    if len(seats) < 4:
        # Fewer than 4 players — no meaningful CO position
        return None
    # Find dealer index in sorted seats
    if dealer_seat not in seats:
        return None
    dealer_idx = seats.index(dealer_seat)
    co_idx = (dealer_idx - 1) % len(seats)
    return seats[co_idx]


def calculate_hud_stats(db_path: str = "poker.db",
                        game_id: str | None = None,
                        use_raw_names: bool = False) -> list[dict]:
    """Calculate VPIP, PFR, ATS for all players.

    Args:
        db_path: Path to SQLite database.
        game_id: If provided, restrict to a single session.
        use_raw_names: If True, return raw player names (for per-session
                       verification). If False, use canonical names.

    Returns:
        List of dicts with keys: player_id, name, hands, vpip, pfr,
        ats_opportunities, ats_attempts, vpip_pct, pfr_pct, ats_pct,
        net_profit.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # ── 1. Fetch hands ──────────────────────────────────────────────────
    hand_sql = """
        SELECT id, game_id, dealer_seat
        FROM hands
    """
    params: list = []
    if game_id:
        hand_sql += " WHERE game_id = ?"
        params.append(game_id)
    hand_sql += " ORDER BY started_at, hand_number"

    cursor.execute(hand_sql, params)
    hands = cursor.fetchall()

    # ── 2. Pre-fetch all events grouped by hand ─────────────────────────
    hand_ids = [h["id"] for h in hands]
    if not hand_ids:
        conn.close()
        return []

    # Build a map: hand_id -> list of event dicts (ordered by time)
    placeholders = ",".join("?" * len(hand_ids))
    cursor.execute(f"""
        SELECT hand_id, event_type, seat, value, event_time
        FROM events
        WHERE hand_id IN ({placeholders})
        ORDER BY hand_id, event_time
    """, hand_ids)
    events_by_hand: dict[str, list] = defaultdict(list)
    for row in cursor.fetchall():
        events_by_hand[row["hand_id"]].append(dict(row))

    # ── 3. Pre-fetch hand_players for seat→player mapping ───────────────
    if use_raw_names:
        cursor.execute(f"""
            SELECT hp.hand_id, hp.player_id, hp.seat, hp.net_gain,
                   p.name
            FROM hand_players hp
            JOIN players p ON hp.player_id = p.id
            WHERE hp.hand_id IN ({placeholders})
        """, hand_ids)
    else:
        cursor.execute(f"""
            SELECT hand_id, player_id, seat, net_gain, name, cid
            FROM v_hand_players
            WHERE hand_id IN ({placeholders})
        """, hand_ids)

    # hand_id -> list of {seat, player_id/cid, name, net_gain}
    players_by_hand: dict[str, list] = defaultdict(list)
    for row in cursor.fetchall():
        d = dict(row)
        if not use_raw_names:
            d["player_id"] = d.pop("cid")
        players_by_hand[d["hand_id"]].append(d)

    conn.close()

    # ── 4. Per-player accumulators ──────────────────────────────────────
    stats: dict[str, dict] = defaultdict(lambda: {
        "name": "",
        "hands": 0,
        "vpip_hands": 0,       # PokerNow: voluntary money on any street
        "conv_vpip_hands": 0,  # Conventional: voluntary money preflop only
        "pfr_hands": 0,
        "ats_opportunities": 0,
        "ats_attempts": 0,
        "net_gain_cents": 0,
        "walk_hands": 0,  # hands excluded from VPIP denominator
        # New stats
        "flop_seen_hands": 0,
        "flop_eligible_hands": 0,
        "bb_faced_raise_hands": 0,
        "bb_defended_hands": 0,
        "bb_steal_faced_hands": 0,
        "bb_folded_to_steal_hands": 0,
        "three_bet_opportunities": 0,
        "three_bet_hands": 0,
    })

    # ── 5. Process each hand ────────────────────────────────────────────
    for hand in hands:
        hand_id = hand["id"]
        dealer_seat = hand["dealer_seat"]
        events = events_by_hand.get(hand_id, [])
        hand_players = players_by_hand.get(hand_id, [])

        if not events or not hand_players:
            continue

        # Map seat -> player info
        seat_to_player = {p["seat"]: p for p in hand_players}
        active_seats = [p["seat"] for p in hand_players]

        # Separate preflop events: everything before the first
        # COMMUNITY_CARDS event (type 9) in the ordered event list.
        # Using position-based boundary (not timestamps) to avoid
        # edge cases where the last preflop action shares a timestamp
        # with the community cards event.
        preflop_events = []
        for e in events:
            if e["event_type"] == _COMMUNITY:
                break
            preflop_events.append(e)

        # Identify SB and BB seats from blind-posting events
        sb_seat = None
        bb_seat = None
        for e in preflop_events:
            if e["event_type"] == _SB_TYPE and sb_seat is None:
                sb_seat = e["seat"]
            elif e["event_type"] == _BB_TYPE and bb_seat is None:
                bb_seat = e["seat"]

        # Detect walk: all non-blind preflop events are folds
        non_blind_events = [e for e in preflop_events
                            if e["event_type"] not in _BLIND_TYPES]
        is_walk = (len(non_blind_events) > 0 and
                   all(e["event_type"] == _FOLD for e in non_blind_events))

        # Determine CO seat
        co_seat = _get_cutoff_seat(active_seats, dealer_seat)

        # ── ATS: determine if pot was unopened when action reaches
        #         each steal position ────────────────────────────────────
        steal_seats = set()
        if co_seat is not None:
            steal_seats.add(co_seat)
        steal_seats.add(dealer_seat)  # BTN
        if sb_seat is not None:
            steal_seats.add(sb_seat)

        # Track action sequence to determine if pot is unopened
        action_events = [e for e in preflop_events
                         if e["event_type"] not in _BLIND_TYPES]

        pot_opened = False  # becomes True once someone limps/calls or raises
        steal_opps: dict[int, bool] = {}
        steal_attempts: dict[int, bool] = {}

        for e in action_events:
            seat = e["seat"]
            etype = e["event_type"]

            if seat in steal_seats and not pot_opened:
                # This steal-position player faces an unopened pot
                steal_opps[seat] = True
                if etype in _PFR_TYPES:  # BET = actual raise = steal attempt
                    steal_attempts[seat] = True

            # Any non-fold action opens the pot (limp, call, raise, all-in)
            if etype != _FOLD:
                pot_opened = True

        # ── Hand-level flags for new stats ────────────────────────────────
        has_flop = any(e["event_type"] == _COMMUNITY for e in events)

        # Track who folded preflop (for flop-seen calculation)
        preflop_folders = {e["seat"] for e in preflop_events
                          if e["event_type"] == _FOLD}

        # Find the first preflop open raiser (for BB defense + 3-bet)
        first_raiser_seat = None
        for e in action_events:
            if e["event_type"] in _PFR_TYPES:
                first_raiser_seat = e["seat"]
                break

        # ── Per-player stats for this hand ──────────────────────────────
        for player_info in hand_players:
            seat = player_info["seat"]
            pid = player_info["player_id"]

            s = stats[pid]
            s["name"] = player_info["name"]
            s["hands"] += 1
            s["net_gain_cents"] += (player_info["net_gain"] or 0)

            if is_walk:
                s["walk_hands"] += 1
                if seat in steal_opps:
                    s["ats_opportunities"] += 1
                    if seat in steal_attempts:
                        s["ats_attempts"] += 1
                continue  # skip VPIP/PFR for walks

            # Preflop actions for this player (used by both VPIP variants + PFR)
            player_preflop = [e for e in preflop_events
                              if e["seat"] == seat
                              and e["event_type"] in _VPIP_TYPES]

            # Conventional VPIP: voluntary money preflop only
            # RAISE(7)=call/limp, BET(8)=raise, ALL_IN(16)=all-in
            conv_vpip = len(player_preflop) > 0

            # PokerNow VPIP: voluntary money on ANY street
            # BB checking preflop but betting/calling postflop = VPIP
            player_money_any = [e for e in events
                                if e["seat"] == seat
                                and e["event_type"] in _VPIP_TYPES]
            pn_vpip = len(player_money_any) > 0

            # PFR: did this player raise preflop?
            # Only BET(8) is a true raise in PokerNow encoding
            pfr = any(e["event_type"] in _PFR_TYPES for e in player_preflop)

            if pn_vpip:
                s["vpip_hands"] += 1
            if conv_vpip:
                s["conv_vpip_hands"] += 1
            if pfr:
                s["pfr_hands"] += 1

            # ATS
            if seat in steal_opps:
                s["ats_opportunities"] += 1
                if seat in steal_attempts:
                    s["ats_attempts"] += 1

            # ── Flop Seen %: player didn't fold before community cards ──
            s["flop_eligible_hands"] += 1
            if has_flop and seat not in preflop_folders:
                s["flop_seen_hands"] += 1

            # ── BB Defense %: BB faces a raise and calls/raises ──────────
            if seat == bb_seat and first_raiser_seat is not None and first_raiser_seat != bb_seat:
                s["bb_faced_raise_hands"] += 1
                # Find BB's response after the raise
                saw_raise = False
                for e in action_events:
                    if e["event_type"] in _PFR_TYPES and e["seat"] == first_raiser_seat:
                        saw_raise = True
                    if saw_raise and e["seat"] == bb_seat:
                        if e["event_type"] != _FOLD:
                            s["bb_defended_hands"] += 1
                        break

            # ── BB Fold to Steal %: BB folds to a steal-position raise ───
            if (seat == bb_seat and first_raiser_seat is not None
                    and first_raiser_seat in steal_seats
                    and first_raiser_seat != bb_seat):
                s["bb_steal_faced_hands"] += 1
                saw_steal = False
                for e in action_events:
                    if e["event_type"] in _PFR_TYPES and e["seat"] == first_raiser_seat:
                        saw_steal = True
                    if saw_steal and e["seat"] == bb_seat:
                        if e["event_type"] == _FOLD:
                            s["bb_folded_to_steal_hands"] += 1
                        break

            # ── 3-Bet %: re-raise after an initial open raise ────────────
            if first_raiser_seat is not None and seat != first_raiser_seat:
                # Player had an opportunity to 3-bet if they acted after the open
                saw_open = False
                counted = False
                for e in action_events:
                    if e["event_type"] in _PFR_TYPES and not saw_open:
                        saw_open = True
                        continue
                    if saw_open and e["seat"] == seat:
                        s["three_bet_opportunities"] += 1
                        if e["event_type"] in _PFR_TYPES or e["event_type"] == _ET["ALL_IN"]:
                            s["three_bet_hands"] += 1
                        counted = True
                        break
                    if saw_open and e["event_type"] in _PFR_TYPES:
                        # Someone else 3-bet before this player acted;
                        # this player no longer has a simple 3-bet opportunity
                        break

    # ── 6. Compute percentages ──────────────────────────────────────────
    result = []
    for pid, s in stats.items():
        vpip_denom = s["hands"] - s["walk_hands"]
        result.append({
            "player_id": pid,
            "name": s["name"],
            "hands": s["hands"],
            "vpip_hands": s["vpip_hands"],
            "conv_vpip_hands": s["conv_vpip_hands"],
            "pfr_hands": s["pfr_hands"],
            "ats_opportunities": s["ats_opportunities"],
            "ats_attempts": s["ats_attempts"],
            "vpip_pct": (s["vpip_hands"] / vpip_denom * 100) if vpip_denom > 0 else 0,
            "conv_vpip_pct": (s["conv_vpip_hands"] / vpip_denom * 100) if vpip_denom > 0 else 0,
            "pfr_pct": (s["pfr_hands"] / s["hands"] * 100) if s["hands"] > 0 else 0,
            "ats_pct": (s["ats_attempts"] / s["ats_opportunities"] * 100)
                       if s["ats_opportunities"] > 0 else None,
            "net_profit": s["net_gain_cents"] / 100.0,
            # New stats
            "flop_seen_hands": s["flop_seen_hands"],
            "flop_eligible_hands": s["flop_eligible_hands"],
            "flop_seen_pct": (s["flop_seen_hands"] / s["flop_eligible_hands"] * 100)
                             if s["flop_eligible_hands"] > 0 else 0,
            "bb_faced_raise_hands": s["bb_faced_raise_hands"],
            "bb_defended_hands": s["bb_defended_hands"],
            "bb_defend_pct": (s["bb_defended_hands"] / s["bb_faced_raise_hands"] * 100)
                             if s["bb_faced_raise_hands"] > 0 else None,
            "bb_steal_faced_hands": s["bb_steal_faced_hands"],
            "bb_folded_to_steal_hands": s["bb_folded_to_steal_hands"],
            "bb_fold_to_steal_pct": (s["bb_folded_to_steal_hands"] / s["bb_steal_faced_hands"] * 100)
                                    if s["bb_steal_faced_hands"] > 0 else None,
            "three_bet_opportunities": s["three_bet_opportunities"],
            "three_bet_hands": s["three_bet_hands"],
            "three_bet_pct": (s["three_bet_hands"] / s["three_bet_opportunities"] * 100)
                             if s["three_bet_opportunities"] > 0 else None,
        })

    # Sort by net profit descending
    result.sort(key=lambda x: x["net_profit"], reverse=True)
    return result
