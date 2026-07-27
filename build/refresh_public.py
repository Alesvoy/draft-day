#!/usr/bin/env python3
"""Refresh rankings from public, no-auth sources and report exactly what moved.

  ECR / tier / team / bye / fpid  FantasyPros consensus cheatsheet (var ecrData)
  ADP                             Fantasy Football Calculator (real 14-team drafts)

Projections are NOT refreshed: FantasyPros gates them to 10 rows for anonymous
requests, and every other free source uses a different methodology that would
rebuild the tiers rather than update them. proj_pts is what natural_break_tiers
runs on, so swapping it is a decision, not a refresh -- see --check.

    python3 build/refresh_public.py --check     # report drift, write nothing
    python3 build/refresh_public.py             # write rankings_std.csv + snapshot
"""
import argparse, csv, io, json, os, re, sys, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
ECR_URL = "https://www.fantasypros.com/nfl/rankings/consensus-cheatsheets.php"
ADP_URL = "https://fantasyfootballcalculator.com/api/v1/adp/standard?teams={teams}&year={year}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
FIELDS = ["fpid", "name", "team", "pos", "bye", "ecr", "adp", "ecr_vs_adp", "rank_std", "fp_tier"]
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def key(name):
    """Join key: drop punctuation and generational suffixes, casefold.
    'D.J. Moore' and 'DJ Moore' collapse; 'Kenneth Walker III' loses the III."""
    parts = re.sub(r"[^a-z ]", "", name.lower()).split()
    return " ".join(p for p in parts if p not in SUFFIXES)


def fetch_ecr():
    html = get(ECR_URL)
    m = re.search(r"var\s+ecrData\s*=\s*(\{.*?\});\s*\n", html, re.S)
    if not m:
        sys.exit("ERROR: ecrData block not found -- FantasyPros changed the page")
    d = json.loads(m.group(1))
    if d.get("scoring") != "STD":
        sys.exit(f"ERROR: expected STD scoring, page served {d.get('scoring')!r}")
    return d


def fetch_adp(teams, year):
    d = json.loads(get(ADP_URL.format(teams=teams, year=year)))
    if d.get("status") != "Success":
        sys.exit(f"ERROR: FFC returned {d.get('status')!r} for teams={teams}")
    return {key(p["name"]): p["adp"] for p in d["players"]}, d.get("meta", {})


def load_existing(path, kfield="name"):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {key(r[kfield]): r for r in csv.DictReader(f)}


def build_rows(ecr, adp):
    rows = []
    for p in ecr["players"]:
        name = p["player_name"].strip()
        a = adp.get(key(name))
        e = p["rank_ecr"]
        rows.append({
            "fpid": p.get("player_id") or "",
            "name": name,
            "team": (p.get("player_team_id") or "").strip(),
            "pos": p["player_position_id"],
            "bye": p.get("player_bye_week") or "",
            "ecr": e,
            "adp": round(a, 1) if a else "",
            "ecr_vs_adp": round(a - e, 1) if a else "",
            "rank_std": p.get("rank_std") or "",
            "fp_tier": p.get("tier") or "",
        })
    return rows


def report(rows, old, proj, top=100):
    """Drift report. The projection join is the one that can silently break the
    board: a miss nulls proj_pts, which drops the player out of pos_tier and
    shifts every tier below them -- indistinguishable from real movement."""
    missing = [r["name"] for r in rows if r["ecr"] and int(r["ecr"]) <= top and key(r["name"]) not in proj]
    moved = []
    for r in rows:
        o = old.get(key(r["name"]))
        if o and o["ecr"]:
            d = int(r["ecr"]) - float(o["ecr"])
            if abs(d) >= 5 and float(o["ecr"]) <= top:
                moved.append((d, r["name"], float(o["ecr"]), r["ecr"]))
    new_names = [r["name"] for r in rows if key(r["name"]) not in old]
    print(f"  players fetched         {len(rows)}")
    print(f"  new to the board        {len(new_names)}" + (f"  ({', '.join(new_names[:5])}...)" if new_names else ""))
    print(f"  moved >=5 in top {top}    {len(moved)}")
    for d, n, a, b in sorted(moved, key=lambda x: -abs(x[0]))[:15]:
        print(f"     {n:26} {a:6.0f} -> {b:<4} ({d:+.0f})")
    if missing:
        print(f"\n  !! {len(missing)} of the top {top} have NO projection -- they would lose their tier:")
        for n in missing[:20]:
            print(f"       {n}")
        print("     Fix the name join before writing, or the board's tiers will shift for the wrong reason.")
    else:
        print(f"  projection join         OK (every top-{top} player matched)")
    return not missing


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--teams", type=int, default=14, help="ADP league size (FFC supports 12 and 14 only)")
    ap.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--check", action="store_true", help="report drift and exit without writing")
    ap.add_argument("--top", type=int, default=100, help="depth that must be clean to write")
    a = ap.parse_args()

    ecr = fetch_ecr()
    adp, meta = fetch_adp(a.teams, a.year)
    print(f"ECR   {ecr['last_updated']}  {ecr['total_experts']} experts  {ecr['scoring']}  season {ecr['year']}")
    print(f"ADP   {meta.get('total_drafts')} drafts  {meta.get('teams')}-team {meta.get('type')}  "
          f"{meta.get('start_date')}..{meta.get('end_date')}")

    rows = build_rows(ecr, adp)
    old = load_existing(os.path.join(DATA, "rankings_std.csv"))
    proj = load_existing(os.path.join(DATA, "projections_std.csv"))
    print(f"\nDRIFT vs data/rankings_std.csv")
    clean = report(rows, old, proj, a.top)

    if a.check:
        print("\n--check: nothing written.")
        return
    if not clean:
        sys.exit("\nrefusing to write while top-N players lack projections (use --check to inspect)")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    out = io.StringIO()
    w = csv.DictWriter(out, FIELDS)
    w.writeheader()
    w.writerows(rows)
    text = out.getvalue()
    snap = os.path.join(DATA, "snapshots", str(a.year), stamp)
    os.makedirs(snap, exist_ok=True)
    for path in (os.path.join(DATA, "rankings_std.csv"), os.path.join(snap, "rankings_std.csv")):
        with open(path, "w") as f:
            f.write(text)
    print(f"\nwrote data/rankings_std.csv ({len(rows)} rows) + snapshot {stamp}")
    print("next: python3 build/build_board.py && python3 build/make_study.py && python3 build/make_app.py")


if __name__ == "__main__":
    main()
