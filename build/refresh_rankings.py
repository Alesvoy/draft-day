#!/usr/bin/env python3
"""Refresh the Standard rankings spine from FantasyPros' current 2026 pages.

The consensus page exposes the complete ECR data set (rank, team, position,
bye, rank standard deviation, tier, and any current ECR-vs-ADP deltas). Its
aggregate ADP table is registration-fenced, so FantasyPros does not publicly
provide a bulk ADP export. The script uses the source's current ADP delta when
it is supplied and otherwise retains the last known ADP from the existing CSV.
That preserves the app's ADP-based draft logic without inventing missing data.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "rankings_std.csv"
ECR_URL = "https://www.fantasypros.com/nfl/rankings/consensus-cheatsheets.php?export=xls"
USER_AGENT = "Fantasy-Draft-Day-Tool/1.0 (+https://github.com/Alesvoy/draft-day)"


def fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def consensus_players() -> tuple[dict, list[dict]]:
    page = fetch(ECR_URL)
    prefix = "var ecrData = "
    start = page.find(prefix)
    if start < 0:
        raise RuntimeError("FantasyPros consensus payload was not found")
    data, _ = json.JSONDecoder().raw_decode(page[start + len(prefix):])
    if data.get("year") != "2026" or data.get("scoring") != "STD":
        raise RuntimeError(
            "Expected 2026 Standard FantasyPros rankings; got "
            f"year={data.get('year')!r}, scoring={data.get('scoring')!r}"
        )
    players = data.get("players", [])
    if not players:
        raise RuntimeError("FantasyPros consensus payload contains no players")
    return data, players


def format_delta(ecr: int, adp: int | None) -> str:
    if adp is None:
        return ""
    delta = adp - ecr
    return f"+{delta}" if delta > 0 else str(delta)


def prior_adps(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open(newline="") as source:
        return {
            row["name"]: int(row["adp"])
            for row in csv.DictReader(source)
            if row.get("adp")
        }


def build_rows(players: list[dict], fallback_adps: dict[str, int]) -> list[dict]:

    rows = []
    for p in players:
        ecr = int(p["rank_ecr"])
        current_delta = p.get("player_ecr_delta")
        adp = (ecr + int(current_delta) if current_delta is not None
               else fallback_adps.get(p["player_name"]))
        rows.append({
            "name": p["player_name"],
            "team": p["player_team_id"],
            "pos": p["player_position_id"],
            "bye": p["player_bye_week"],
            "ecr": ecr,
            "adp": "" if adp is None else adp,
            "ecr_vs_adp": format_delta(ecr, adp),
            "rank_std": f"{float(p['rank_std']):.2f}",
            "fp_tier": int(p["tier"]),
        })
    return rows


def write_csv(rows: list[dict], output: Path) -> None:
    fields = ["name", "team", "pos", "bye", "ecr", "adp", "ecr_vs_adp", "rank_std", "fp_tier"]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    output.write_text(buffer.getvalue())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data, players = consensus_players()
    rows = build_rows(players, prior_adps(args.output))
    write_csv(rows, args.output)
    adp_count = sum(bool(row["adp"]) for row in rows)
    print(
        f"Wrote {args.output} with {len(rows)} 2026 Standard rankings; "
        f"{adp_count} ADP values (current source deltas applied where available). "
        f"FantasyPros consensus last updated {data.get('last_updated')}."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
