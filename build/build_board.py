#!/usr/bin/env python3
"""
Build the frozen draft board. Defaults to a 14-team, 0-PPR (true standard)
league, and ALSO freezes a value layer for every (scoring x team-count) combo
the app's setup screen offers (8/10/12/14/16 teams x std/half/full PPR).

Pipeline (matches the agreed design):
  1. INGEST  consensus rankings + ADP (FantasyPros, Standard) as the FIXED order.
  2. JOIN    Standard projected points + projected receptions onto each player.
  3. COMPUTE a layer on top -- VOR, value-vs-ADP, tiers, ceiling/risk flags --
             for the default config (legacy fields) AND per-combo matrices.
             These are DERIVED deterministically, never hand-assigned.
  4. FREEZE  the result to board.json (single source of truth).

Nothing here re-ranks players. ECR is the spine; everything else is a column
that sits on top of it. Re-run any time the CSVs are refreshed.
"""
import csv, json, os, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")

# ---------------------------------------------------------------------------
# LEAGUE CONFIG  -- the only knobs. Tune here, re-run, board updates.
# ---------------------------------------------------------------------------
LEAGUE = {
    "teams": 14,
    "scoring": "Standard (0 PPR)",
    "starters": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1},
    "flex_positions": ["RB", "WR", "TE"],
}

# The app lets the user pick teams + scoring at setup, so the board carries a
# value layer for every combo. ECR/ADP stay a single Standard spine (per the
# guide: scoring shifts top-player ranks barely at all; lineup structure is
# what actually moves value).
TEAM_OPTIONS = [8, 10, 12, 14, 16]
SCORING_OPTIONS = ["std", "half", "full"]
SCORING_LABELS = {"std": "Standard (0 PPR)", "half": "Half PPR", "full": "Full PPR"}
REC_PPR = {"std": 0.0, "half": 0.5, "full": 1.0}  # points per reception

# Share of the FLEX slots each position absorbs, per scoring. Guide p27-28:
# 0-PPR pushes FLEX toward RB (their floor wins standard); full PPR flips it --
# WRs outscore RBs at the flex. Fractions chosen to reproduce the historical
# 14-team standard baselines exactly (RB 37 / WR 34).
FLEX_SHARE = {
    "std":  {"RB": 9 / 14, "WR": 6 / 14},
    "half": {"RB": 7.5 / 14, "WR": 7.5 / 14},
    "full": {"RB": 6 / 14, "WR": 9 / 14},
}


def replacement_ranks(teams, scoring):
    """Replacement RANK per position = where the position becomes "freely
    available." QB/TE/K/DST = one starter per team; RB/WR = starters plus
    their scoring-dependent share of the FLEX slots."""
    s = LEAGUE["starters"]
    flex_slots = teams * s["FLEX"]
    return {
        "QB": teams * s["QB"], "TE": teams * s["TE"],
        "K": teams * s["K"], "DST": teams * s["DST"],
        "RB": teams * s["RB"] + round(FLEX_SHARE[scoring]["RB"] * flex_slots),
        "WR": teams * s["WR"] + round(FLEX_SHARE[scoring]["WR"] * flex_slots),
    }


# The formula must reproduce the original hand-derived 14-team standard table.
REPLACEMENT_RANK = replacement_ranks(14, "std")
assert REPLACEMENT_RANK == {"QB": 14, "RB": 37, "WR": 34, "TE": 14, "K": 14, "DST": 14}, REPLACEMENT_RANK
assert replacement_ranks(14, "half")["RB"] == 36  # pins banker's rounding on the 7.5 tie

# Tier sensitivity: a new tier starts when the points drop-off between two
# consecutive players exceeds mean(gap) + SENS*stdev(gap). Higher = fewer tiers.
TIER_SENS = 0.75

# JJ Zachariason "Late-Round" positional game theory, surfaced live in the app.
STRATEGY_NOTES = {
    "QB": ("Konami Code: rushing QBs (Allen, Jackson, J. Daniels, Hurts, Maye) "
           "carry a weekly rushing floor. Get one of the elite tier OR wait and "
           "stream -- avoid the pocket-passer dead zone in the middle rounds."),
    "RB": ("0-PPR + 14 teams = RB scarcity is REAL. Anchor early (Hero-RB) and "
           "secure starters before the tier cliffs. Target three-down backs and "
           "goal-line roles; their floor wins standard leagues."),
    "WR": ("Deepest position -- you can wait if you've anchored RB. Chase target "
           "share and yards-per-route-run. In the late rounds throw darts at "
           "high-ceiling (high-variance) WRs, not safe floors."),
    "TE": ("Elite TE (McBride/Bowers) or punt. Avoid the TE dead zone (~rounds "
           "6-10). If you miss the top tier, wait and take a value-vs-ADP faller."),
    "K": ("Streaming position. Draft last. Never reach."),
    "DST": ("Streaming position. Draft late, target good Week 1 matchups."),
}

# Per-scoring strategy notes shown in the app once a format is chosen. "{teams}"
# is substituted live. std == the legacy notes (with the team count templated);
# only RB/WR actually change with scoring (guide: QB/TE strategy is
# format-independent).
STRATEGY_NOTES_M = {
    "std": dict(STRATEGY_NOTES, **{
        "RB": STRATEGY_NOTES["RB"].replace("0-PPR + 14 teams", "0-PPR + {teams} teams"),
    }),
    "half": dict(STRATEGY_NOTES, **{
        "RB": ("Half PPR in a {teams}-team league: RB scarcity still bites, and "
               "pass-catching backs (REC-BACK) add a steady half-point-per-catch "
               "floor. Anchor early (Hero-RB) and secure starters before the tier "
               "cliffs; three-down roles still rule."),
        "WR": ("Deep position, and receptions now pay. Chase target share and "
               "yards-per-route-run; WRs are a fine flex alongside RBs. Late "
               "rounds: throw darts at high-ceiling WRs, not safe floors."),
    }),
    "full": dict(STRATEGY_NOTES, **{
        "RB": ("Full PPR in a {teams}-team league: receptions make satellite and "
               "pass-catching backs startable, and WRs outscore RBs at the flex. "
               "Hero-RB and Zero-RB are both live — don't force early RBs "
               "without receiving work."),
        "WR": ("WRs gain the most in full PPR — a WR-heavy start is a winning "
               "build and the flex leans WR. Chase target share above all. Late "
               "rounds: high-ceiling darts over safe floors."),
    }),
}

# One-liner surfaced on the Strategy tab explaining the flex lean per format.
FLEX_NOTES = {
    "std": "Flex leans RB in standard — their floor wins 0-PPR. Baked into the VOR baselines.",
    "half": "Flex is balanced RB/WR in half PPR. Baked into the VOR baselines.",
    "full": "Flex leans WR in full PPR — WRs outscore RBs per game. Baked into the VOR baselines.",
}

ADP_NOTE = ("Rankings/ADP are standard-market; PPR shifts the value columns "
            "(VOR, tiers), not the board order.")


def num(s):
    s = (s or "").strip()
    if s == "":
        return None
    s = s.replace("+", "")
    try:
        return float(s) if ("." in s) else int(s)
    except ValueError:
        return None


def natural_break_tiers(values_desc, max_size=6):
    """Assign tier numbers (1=best) by detecting gaps in a descending value list.

    Pure gap-detection collapses smooth declines (e.g. QB after the elite tier) into
    one giant useless tier, so we also force a new tier once a tier hits max_size --
    real cliffs where they exist, digestible bands where the curve is smooth.
    """
    if len(values_desc) <= 1:
        return [1] * len(values_desc)
    gaps = [values_desc[i] - values_desc[i + 1] for i in range(len(values_desc) - 1)]
    mean_g = statistics.mean(gaps)
    std_g = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    threshold = mean_g + TIER_SENS * std_g
    tiers, t, count = [1], 1, 1
    for g in gaps:
        if g > threshold or count >= max_size:
            t += 1
            count = 1
        else:
            count += 1
        tiers.append(t)
    return tiers


def load_rankings():
    rows = []
    with open(os.path.join(DATA, "rankings_std.csv")) as f:
        for r in csv.DictReader(f):
            rows.append({
                "name": r["name"].strip(),
                "team": r["team"].strip(),
                "pos": r["pos"].strip(),
                "bye": num(r["bye"]),
                "ecr": num(r["ecr"]),
                "adp": num(r["adp"]),
                "value_vs_adp": num(r["ecr_vs_adp"]),  # + = falls to you (value)
                "rank_std": num(r["rank_std"]),        # higher = wider outcomes
                "fp_tier": num(r["fp_tier"]),
            })
    return rows


def load_projections():
    """Returns (proj_pts by name, projected receptions by name).

    The rec column is optional (older pulls lack it) -- without it the board is
    built with ppr_available=False and the app disables the PPR options."""
    proj, rec = {}, {}
    with open(os.path.join(DATA, "projections_std.csv")) as f:
        for r in csv.DictReader(f):
            name = r["name"].strip()
            proj[name] = num(r["proj_pts"])
            if "rec" in r:
                rec[name] = num(r["rec"])
    return proj, rec


def load_rookies():
    s = set()
    path = os.path.join(DATA, "rookies_2026.csv")
    if os.path.exists(path):
        with open(path) as f:
            for r in csv.DictReader(f):
                s.add(r["name"].strip())
    return s


def load_splits():
    out = {}
    with open(os.path.join(DATA, "proj_splits.csv")) as f:
        for r in csv.DictReader(f):
            out[r["name"].strip()] = {
                "rec_yds": num(r["rec_yds"]), "rec_td": num(r["rec_td"]),
                "rush_yds": num(r["rush_yds"]), "rush_td": num(r["rush_td"]),
            }
    return out


# PDF strategy thresholds (JJ Zachariason "Late-Round" principles, encoded as data rules)
REC_BACK_PTS = 50      # RB receiving points (0-PPR: yds/10 + recTD*6) above this = pass-game back
KONAMI_RUSH_PTS = 60   # QB rushing points above this = mobile/Konami floor
POCKET_RUSH_PTS = 30   # QB rushing points below this = pocket passer (historically fades)
COMMITTEE_ECR_GAP = 45 # two same-team RBs within this ECR gap = ambiguous backfield (upside)


def add_strategy_tags(players):
    """Timeless per-position strategy from the guide, recomputed on the CURRENT board."""
    splits = load_splits()
    for p in players:
        s = splits.get(p["name"], {})
        ry, rt = s.get("rec_yds"), s.get("rec_td")
        uy, ut = s.get("rush_yds"), s.get("rush_td")
        p["rec_pts"] = round(ry/10 + (rt or 0)*6, 1) if ry is not None else None
        p["rush_pts"] = round(uy/10 + (ut or 0)*6, 1) if uy is not None else None
        p["strategy"] = []

    # RB: pass-catching backs (JJ's #1 early-RB rule; still real in 0-PPR via yards/TDs)
    for p in players:
        if p["pos"] == "RB" and p["rec_pts"] is not None and p["rec_pts"] >= REC_BACK_PTS:
            p["strategy"].append("REC-BACK")

    # RB: ambiguous/committee backfields (JJ's middle-round upside signal) -- two same-team
    # backs drafted close together. Computed from the board, not last year's team list.
    by_team = {}
    for p in players:
        if p["pos"] == "RB":
            by_team.setdefault(p["team"], []).append(p)
    # Only the team's TOP TWO backs count, and only in a relevant backfield (lead is
    # at least a mid-round back): ambiguity is about who the lead is, not deep handcuffs.
    for grp in by_team.values():
        grp.sort(key=lambda x: x["ecr"])
        if len(grp) >= 2 and grp[0]["ecr"] <= 120 and grp[1]["ecr"] - grp[0]["ecr"] <= COMMITTEE_ECR_GAP:
            for x in grp[:2]:
                x["strategy"].append("COMMITTEE")

    # HANDCUFF: the clear backup behind a bell-cow lead back (NOT a committee). Pure
    # contingent value -- a league-winner if the starter goes down. A classic mid/late
    # bench swing. Only when there's a real lead (startable ECR) and a clear gap.
    for grp in by_team.values():
        grp.sort(key=lambda x: x["ecr"])
        if len(grp) >= 2:
            lead = grp[0]
            if lead["ecr"] <= 72:
                # a true bell-cow (top ~3 rounds) can have two viable handcuffs; a
                # lesser lead, just one.
                limit = 2 if lead["ecr"] <= 36 else 1
                for hc in grp[1:1 + limit]:
                    if hc["ecr"] - lead["ecr"] > COMMITTEE_ECR_GAP:
                        hc["strategy"].append("HANDCUFF")
                        hc["handcuff_to"] = lead["name"]

    # QB: Konami (mobile, has a floor) vs pocket passer (JJ: historically fades on ADP)
    for p in players:
        if p["pos"] == "QB" and p["rush_pts"] is not None:
            if p["rush_pts"] >= KONAMI_RUSH_PTS:
                p["strategy"].append("KONAMI")
            elif p["rush_pts"] < POCKET_RUSH_PTS:
                p["strategy"].append("POCKET")

    # TE: the elite tier ("Bowers/McBride/Kittle, or wait"). Everything below is the dead zone.
    for p in players:
        if p["pos"] == "TE" and p["pos_tier"] == 1:
            p["strategy"].append("ELITE-TE")


def add_context_tags(players):
    """Team/offense context (JJ): mobile-QB volume drag on RBs, passing-offense
    quality and positional competition for pass-catchers. All from the board."""
    for p in players:
        p["context"] = []

    # PASSING environment = QB passing points (total minus rushing). Using total would
    # reward rushing QBs and wrongly flag high-volume pocket-passer offenses (great for
    # WRs) as weak. Mobility (for the RB drag) = QB rushing points.
    qb_proj, qb_rush = {}, {}
    for p in players:
        if p["pos"] == "QB" and p["proj_pts"] is not None:
            passing = p["proj_pts"] - (p["rush_pts"] or 0)
            if passing > qb_proj.get(p["team"], -1):
                qb_proj[p["team"]] = passing
        if p["pos"] == "QB" and p["rush_pts"] is not None:
            qb_rush[p["team"]] = max(qb_rush.get(p["team"], 0), p["rush_pts"])

    # offense quality tiers from QB passing points
    pv = sorted(qb_proj.values())
    hi = pv[int(len(pv) * 0.66)] if pv else 0
    lo = pv[int(len(pv) * 0.33)] if pv else 0

    # same-team pass-catcher competition (drafted-range WR/TE)
    wr_comp = {}
    for p in players:
        if p["pos"] == "WR" and p["ecr"] <= 110:
            wr_comp[p["team"]] = wr_comp.get(p["team"], 0) + 1

    for p in players:
        # RB: mobile QB siphons carries/targets/goal-line work -> volume drag
        if p["pos"] == "RB" and qb_rush.get(p["team"], 0) >= KONAMI_RUSH_PTS:
            p["context"].append("MOBILE-QB")
        # WR/TE: passing-offense quality
        if p["pos"] in ("WR", "TE"):
            off = qb_proj.get(p["team"])
            if off is not None:
                if off >= hi:
                    p["context"].append("GOOD-OFF")
                elif off <= lo:
                    p["context"].append("WEAK-OFF")
        # TE: low WR competition = opportunity (JJ's Engram example)
        if p["pos"] == "TE" and wr_comp.get(p["team"], 0) <= 1:
            p["context"].append("LOW-COMP")
        # WR: crowded corps (3+ drafted-range WRs) = target competition
        if p["pos"] == "WR" and wr_comp.get(p["team"], 0) >= 3:
            p["context"].append("CROWDED")

    # rookies (JJ: first-year players give the highest ceiling in the late rounds)
    rookies = load_rookies()
    for p in players:
        p["rookie"] = p["name"] in rookies
        if p["rookie"]:
            p["context"].append("ROOKIE")


def proj_for(p, scoring):
    """Projected points under a scoring format. PPR is exact math on top of the
    standard projection: half = +0.5/rec, full = +1/rec. Missing rec -> 0 recs
    (deep-bench players only; the build warns if anyone draftable lacks it)."""
    if p["proj_pts"] is None:
        return None
    if scoring == "std":
        return p["proj_pts"]
    return round(p["proj_pts"] + REC_PPR[scoring] * (p["rec"] or 0), 1)


def add_variants(players, ppr_available):
    """Value layer for every (scoring x team-count) combo, stored ALONGSIDE the
    legacy fields -- which stay byte-identical to a pre-config-era build. The
    std/14-team slices are asserted equal to the legacy fields, so the default
    config is structurally the old board."""
    scorings = SCORING_OPTIONS if ppr_available else ["std"]
    positions = set(p["pos"] for p in players)
    repl_rank_m = {s: {} for s in scorings}
    repl_pts_m = {s: {} for s in scorings}

    for p in players:
        p["vor_m"] = {}
        p["value_tier_m"] = {}
        if ppr_available:
            p["proj_m"] = {s: proj_for(p, s) for s in ("half", "full")}
            p["pos_tier_m"] = {}

    for scoring in scorings:
        pts = {p["name"]: proj_for(p, scoring) for p in players}

        # within-position tiers depend on scoring only (same algorithm/sort as legacy)
        if scoring != "std":
            for pos in positions:
                grp = [p for p in players if p["pos"] == pos]
                grp.sort(key=lambda x: (pts[x["name"]] is None, -(pts[x["name"]] or 0), x["ecr"]))
                vals = [pts[g["name"]] for g in grp if pts[g["name"]] is not None]
                tiers = natural_break_tiers(vals) if vals else []
                ti = 0
                for g in grp:
                    if pts[g["name"]] is not None:
                        g["pos_tier_m"][scoring] = tiers[ti]; ti += 1
                    else:
                        g["pos_tier_m"][scoring] = None

        for teams in TEAM_OPTIONS:
            ranks = replacement_ranks(teams, scoring)
            for pos, rank in ranks.items():
                vals = sorted([pts[p["name"]] for p in players
                               if p["pos"] == pos and pts[p["name"]] is not None],
                              reverse=True)
                if vals:
                    repl_pts_m[scoring].setdefault(pos, []).append(round(vals[min(rank, len(vals)) - 1], 1))
                repl_rank_m[scoring].setdefault(pos, []).append(rank)
            base = {pos: v[-1] for pos, v in repl_pts_m[scoring].items()}

            for p in players:
                pv = pts[p["name"]]
                b = base.get(p["pos"])
                p["vor_m"].setdefault(scoring, []).append(
                    round(pv - b, 1) if (pv is not None and b is not None) else None)

            # cross-positional value tiers on this combo's VOR (same sort as legacy)
            cur = [p for p in players if p["vor_m"][scoring][-1] is not None]
            cur.sort(key=lambda x: -x["vor_m"][scoring][-1])
            vt = natural_break_tiers([p["vor_m"][scoring][-1] for p in cur])
            tier_of = {id(p): t for p, t in zip(cur, vt)}
            for p in players:
                p["value_tier_m"].setdefault(scoring, []).append(tier_of.get(id(p)))

    # self-check: the std/14 slice must equal the legacy fields exactly
    i14 = TEAM_OPTIONS.index(14)
    for p in players:
        assert p["vor_m"]["std"][i14] == p["vor"], (p["name"], p["vor_m"]["std"][i14], p["vor"])
        assert p["value_tier_m"]["std"][i14] == p["value_tier"], (p["name"],)
    return repl_rank_m, repl_pts_m


def build():
    players = load_rankings()
    proj, rec = load_projections()

    # 1) JOIN projections (+ projected receptions for the PPR value layer)
    for p in players:
        p["proj_pts"] = proj.get(p["name"])
        p["rec"] = rec.get(p["name"])

    ppr_available = any(v is not None for v in rec.values())
    if ppr_available:
        no_rec = [p for p in players
                  if p["pos"] in ("RB", "WR", "TE") and p["ecr"] is not None
                  and p["ecr"] <= 170 and p["rec"] is None and p["proj_pts"] is not None]
        if no_rec:
            print("WARNING: draftable players missing rec (treated as 0 receptions "
                  "in PPR):")
            for p in no_rec:
                print("  ECR %3d %s (%s)" % (p["ecr"], p["name"], p["pos"]))
    else:
        print("NOTE: no rec column in projections_std.csv -- board built with "
              "ppr_available=false (app will disable Half/Full PPR).")

    # 2) REPLACEMENT points per position (Nth-best projection at that position)
    repl_pts = {}
    for pos, rank in REPLACEMENT_RANK.items():
        pts = sorted([p["proj_pts"] for p in players
                      if p["pos"] == pos and p["proj_pts"] is not None],
                     reverse=True)
        if pts:
            repl_pts[pos] = pts[min(rank, len(pts)) - 1]

    # 3) VOR = projected points above positional replacement
    for p in players:
        base = repl_pts.get(p["pos"])
        if p["proj_pts"] is not None and base is not None:
            p["vor"] = round(p["proj_pts"] - base, 1)
        else:
            p["vor"] = None

    # 4) POSITIONAL rank + within-position tiers (on projected points)
    for pos in set(p["pos"] for p in players):
        grp = [p for p in players if p["pos"] == pos]
        grp.sort(key=lambda x: (x["proj_pts"] is None, -(x["proj_pts"] or 0), x["ecr"]))
        proj_vals = [g["proj_pts"] for g in grp if g["proj_pts"] is not None]
        pos_tiers = natural_break_tiers(proj_vals) if proj_vals else []
        ti = 0
        for i, g in enumerate(grp):
            g["pos_rank"] = "%s%d" % (pos, i + 1)
            if g["proj_pts"] is not None:
                g["pos_tier"] = pos_tiers[ti]; ti += 1
            else:
                g["pos_tier"] = None

    # 5) CROSS-POSITIONAL value tiers (on VOR) -- "is this RB worth the same as that WR?"
    vor_players = sorted([p for p in players if p["vor"] is not None],
                         key=lambda x: -x["vor"])
    vt = natural_break_tiers([p["vor"] for p in vor_players])
    for p, t in zip(vor_players, vt):
        p["value_tier"] = t
    for p in players:
        p.setdefault("value_tier", None)

    # 6) FLAGS (derived, not hand-set)
    stds = [p["rank_std"] for p in players if p["rank_std"] is not None]
    hi_std = statistics.quantiles(stds, n=4)[2] if len(stds) >= 4 else None  # top quartile
    lo_std = statistics.quantiles(stds, n=4)[0] if len(stds) >= 4 else None  # bottom quartile
    for p in players:
        flags = []
        # NOTE: VALUE / REACH are computed live in the app, PICK-RELATIVE (ADP vs your
        # actual pick), not here as a generic expert-vs-market delta. Only volatility
        # flags (SAFE/CEILING) are static.
        s = p["rank_std"]
        if s is not None and hi_std is not None:
            if s >= hi_std: flags.append("CEILING")  # wide range of outcomes
            elif s <= lo_std: flags.append("SAFE")   # narrow, predictable
        p["flags"] = flags

    # 7) PDF STRATEGY TAGS (timeless principles recomputed on current data)
    add_strategy_tags(players)
    add_context_tags(players)

    # 8) VALUE-LAYER VARIANTS for every (scoring x team-count) the app offers.
    # Runs before the final sort so tie-handling matches the legacy pass above.
    repl_rank_m, repl_pts_m = add_variants(players, ppr_available)

    # ORDER by ECR -- the fixed spine. Nothing above re-sorted this.
    players.sort(key=lambda x: x["ecr"])

    board = {
        "meta": {
            "built": str(date.today()),
            "source": "FantasyPros consensus (Standard) + FantasyPros projections (Standard)",
            "scoring": LEAGUE["scoring"],
            "teams": LEAGUE["teams"],
            "starters": LEAGUE["starters"],
            "flex_positions": LEAGUE["flex_positions"],
            "replacement_rank": REPLACEMENT_RANK,
            "replacement_pts": {k: round(v, 1) for k, v in repl_pts.items()},
            "strategy_notes": STRATEGY_NOTES,
            "strategy_thresholds": {
                "rec_back_pts": REC_BACK_PTS, "konami_rush_pts": KONAMI_RUSH_PTS,
                "pocket_rush_pts": POCKET_RUSH_PTS, "committee_ecr_gap": COMMITTEE_ECR_GAP,
            },
            # --- league-config layer (additive; legacy keys above are the 14-team
            # standard defaults and stay byte-identical to pre-config builds) ---
            "team_options": TEAM_OPTIONS,
            "scoring_options": SCORING_OPTIONS if ppr_available else ["std"],
            "scoring_labels": SCORING_LABELS,
            "default_config": {"teams": 14, "scoring": "std", "rounds": 18},
            "ppr_available": ppr_available,
            "replacement_rank_m": repl_rank_m,
            "replacement_pts_m": repl_pts_m,
            "flex_share": {s: {k: round(v, 4) for k, v in FLEX_SHARE[s].items()}
                           for s in (SCORING_OPTIONS if ppr_available else ["std"])},
            "strategy_notes_m": STRATEGY_NOTES_M if ppr_available else {"std": STRATEGY_NOTES_M["std"]},
            "flex_notes": FLEX_NOTES,
            "adp_note": ADP_NOTE,
            "tag_legend": {
                "REC-BACK": "Pass-catching RB (JJ's top early-RB trait)",
                "COMMITTEE": "Ambiguous backfield — middle-round upside",
                "KONAMI": "Mobile QB with a rushing floor",
                "POCKET": "Pocket passer — historically fades vs ADP",
                "ELITE-TE": "Elite TE tier — the only TEs worth taking before the late rounds",
                "HANDCUFF": "Backup to a bell-cow RB — league-winner if the starter goes down",
                "MOBILE-QB": "RB whose mobile QB siphons carries/targets/goal-line work",
                "GOOD-OFF": "Pass-catcher in a strong projected passing offense",
                "WEAK-OFF": "Pass-catcher in a weak offense (TEs here rarely hit)",
                "LOW-COMP": "TE with little same-team WR competition (more targets)",
                "CROWDED": "WR in a crowded receiver room (target competition)",
                "ROOKIE": "First-year player — highest late-round ceiling (JJ)",
            },
            "player_count": len(players),
        },
        "players": players,
    }

    out = os.path.join(ROOT, "board.json")
    with open(out, "w") as f:
        json.dump(board, f, indent=2)
    print("Wrote %s (%d players)" % (out, len(players)))
    print("Replacement pts:", board["meta"]["replacement_pts"])
    return board


if __name__ == "__main__":
    build()
