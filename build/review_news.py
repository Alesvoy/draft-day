#!/usr/bin/env python3
"""Review or update ambiguous player-risk events collected by refresh_data.py."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "risk_events.json"


def validate_scenarios(scenarios: list[dict]) -> None:
    if not scenarios:
        raise ValueError("approved events require at least one scenario")
    total = sum(float(s.get("probability", 0)) for s in scenarios)
    if abs(total - 1.0) > 0.0001:
        raise ValueError(f"scenario probabilities total {total}, expected 1.0")
    for scenario in scenarios:
        games = float(scenario.get("games_missed", 0)); multiplier = float(scenario.get("performance_multiplier", 1))
        if not 0 <= games <= 17: raise ValueError("games_missed must be between 0 and 17")
        if not 0 <= multiplier <= 1.5: raise ValueError("performance_multiplier must be between 0 and 1.5")


def load_events() -> list[dict]:
    return json.loads(EVENTS.read_text()) if EVENTS.exists() else []


def save_events(events: list[dict]) -> None:
    temp = EVENTS.with_suffix(".tmp"); temp.write_text(json.dumps(events, indent=2) + "\n"); temp.replace(EVENTS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list pending events")
    parser.add_argument("--event")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--display-only", action="store_true")
    action.add_argument("--resolve", action="store_true")
    action.add_argument("--approve", type=Path, metavar="SCENARIOS_JSON")
    args = parser.parse_args()
    events = load_events()
    if args.list or not args.event:
        pending = [e for e in events if e.get("review_state") == "pending"]
        for event in pending:
            print(f"{event['event_id']}  FP:{event['fpid']}  {event['type']}  {event['summary']}")
        print(f"{len(pending)} pending event(s)")
        return
    event = next((e for e in events if e["event_id"] == args.event), None)
    if not event: raise SystemExit(f"unknown event: {args.event}")
    if args.resolve:
        event.update(status="resolved", review_state="display_only", scenarios=[])
    elif args.display_only:
        event.update(review_state="display_only", scenarios=[])
    elif args.approve:
        scenarios = json.loads(args.approve.read_text()); validate_scenarios(scenarios)
        event.update(review_state="approved", scenarios=scenarios)
    else:
        raise SystemExit("choose --approve, --display-only, or --resolve")
    event["verified_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    save_events(events); print(f"Updated {event['event_id']}: {event['review_state']}")


if __name__ == "__main__":
    main()
