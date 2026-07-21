"""Transparent historical calibration and current-event forecast overlays."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


MIN_COHORT = 30
DEFAULT_RANGES = {
    "QB": (-0.28, 0.00, 0.16), "RB": (-0.48, 0.00, 0.25),
    "WR": (-0.42, 0.00, 0.24), "TE": (-0.43, 0.00, 0.24),
    "K": (-0.30, 0.00, 0.18), "DST": (-0.32, 0.00, 0.20),
}
RISK_ORDER = {"unknown": -1, "low": 0, "medium": 1, "high": 2}


def as_number(value, default=None):
    try:
        if value in (None, ""): return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_time(value: str | None):
    if not value: return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def quantile(values: list[float], q: float) -> float:
    if not values: return 0.0
    values = sorted(values); at = (len(values) - 1) * q
    lo, hi = int(at), min(int(at) + 1, len(values) - 1); fraction = at - lo
    return values[lo] * (1 - fraction) + values[hi] * fraction


def weighted_quantile(values: list[tuple[float, float]], q: float) -> float:
    if not values: return 1.0
    ordered = sorted(values); target = q * sum(weight for _, weight in ordered); seen = 0.0
    for value, weight in ordered:
        seen += weight
        if seen >= target: return value
    return ordered[-1][0]


def ecr_band(ecr: float | None) -> int:
    if ecr is None: return 3
    if ecr <= 24: return 0
    if ecr <= 72: return 1
    if ecr <= 144: return 2
    return 3


def age_band(pos: str, age: float | None) -> int:
    if age is None: return 1
    cuts = (24, 27) if pos == "RB" else (25, 29)
    return 0 if age < cuts[0] else 1 if age < cuts[1] else 2


def availability_band(games: float | None) -> int:
    if games is None: return 1
    missed = 17 - games
    return 0 if missed <= 1 else 1 if missed <= 5 else 2


def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def load_history(path: Path) -> list[dict]:
    if not path.exists(): return []
    with path.open(newline="") as source:
        records = list(csv.DictReader(source))
    by_player = defaultdict(list)
    for row in records:
        projected, actual = as_number(row.get("projected_std")), as_number(row.get("actual_std"))
        if not row.get("fpid") or not row.get("pos") or not projected or actual is None: continue
        row = dict(row); row.update(
            projected=projected, actual=actual, age=as_number(row.get("age")),
            ecr=as_number(row.get("ecr")), games=as_number(row.get("games")), season=int(row["season"]),
            residual=max(-1.0, min(1.5, (actual - projected) / projected)),
        ); by_player[row["fpid"]].append(row)
    out = []
    for player_rows in by_player.values():
        player_rows.sort(key=lambda x: x["season"])
        for index, row in enumerate(player_rows):
            prior = [x["games"] for x in player_rows[max(0, index - 2):index] if x["games"] is not None]
            row["prior_games"] = sum(prior) / len(prior) if prior else None; out.append(row)
    return out


def cohort(history: list[dict], player: dict, prior_games: float | None) -> tuple[list[dict], str]:
    pos, eband, aband, vband = player["pos"], ecr_band(player.get("ecr")), age_band(player["pos"], player.get("age")), availability_band(prior_games)
    levels = [
        (lambda r: r["pos"] == pos and ecr_band(r["ecr"]) == eband and age_band(pos, r["age"]) == aband and availability_band(r["prior_games"]) == vband, "position/ecr/age/availability"),
        (lambda r: r["pos"] == pos and ecr_band(r["ecr"]) == eband and age_band(pos, r["age"]) == aband, "position/ecr/age"),
        (lambda r: r["pos"] == pos and ecr_band(r["ecr"]) == eband, "position/ecr"),
        (lambda r: r["pos"] == pos, "position"),
    ]
    for predicate, label in levels:
        matches = [row for row in history if predicate(row)]
        if len(matches) >= MIN_COHORT: return matches, label
    matches = [row for row in history if row["pos"] == pos]
    return matches, "position fallback"


def validate_events(events: list[dict]) -> None:
    for event in events:
        if event.get("review_state") != "approved": continue
        scenarios = event.get("scenarios") or []
        total = sum(as_number(s.get("probability"), 0) for s in scenarios)
        if not scenarios or abs(total - 1.0) > 0.0001:
            raise ValueError(f"{event.get('event_id')}: approved scenario probabilities must total 1.0")
        for scenario in scenarios:
            games = as_number(scenario.get("games_missed"), -1)
            multiplier = as_number(scenario.get("performance_multiplier"), -1)
            if not 0 <= games <= 17 or not 0 <= multiplier <= 1.5:
                raise ValueError(f"{event.get('event_id')}: invalid scenario values")


def validate_release_status(players: list[dict], data_dir: str | Path, now=None) -> None:
    data_dir = Path(data_dir); status = load_json(data_dir / "data_status.json", {})
    if not status: return  # legacy checked-in inputs remain buildable until first API refresh
    fetched = parse_time(status.get("fetched_at"))
    now = now or datetime.now(timezone.utc)
    if not fetched or (now - fetched).days > 14:
        raise ValueError("current rankings data is missing a valid timestamp or is more than 14 days old")
    unmapped = [p["name"] for p in players if p.get("ecr", 999) <= 300 and not p.get("fpid")]
    if unmapped:
        raise ValueError("top-300 players missing FantasyPros IDs: " + ", ".join(unmapped[:10]))


def active_overlay(event: dict, projection_as_of) -> bool:
    if event.get("review_state") != "approved" or event.get("status") == "resolved": return False
    if event.get("projection_incorporation") == "priced": return False
    published = parse_time(event.get("published_at"))
    return not projection_as_of or not published or published > projection_as_of


def risk_level(prior_games: float | None, events: list[dict], event_type: str) -> str:
    relevant = [e for e in events if e.get("type") == event_type and e.get("status") != "resolved"]
    if any(e.get("review_state") == "approved" for e in relevant): return "high"
    if relevant: return "medium"
    if event_type == "injury" and prior_games is not None:
        return "high" if prior_games <= 12 else "medium" if prior_games < 15.5 else "low"
    return "low"


def max_risk(*levels: str) -> str:
    return max(levels, key=lambda value: RISK_ORDER[value])


def add_forecasts(players: list[dict], data_dir: str | Path, scorings: dict[str, float]) -> dict:
    data_dir = Path(data_dir); history = load_history(data_dir / "player_history.csv")
    current_meta = {str(p.get("fpid", "")): p for p in load_json(data_dir / "players.json", [])}
    news_by_player = defaultdict(list)
    for item in load_json(data_dir / "news_current.json", []): news_by_player[str(item.get("fpid", ""))].append(item)
    events = load_json(data_dir / "risk_events.json", []); validate_events(events)
    events_by_player = defaultdict(list)
    for event in events: events_by_player[str(event.get("fpid", ""))].append(event)
    status = load_json(data_dir / "data_status.json", {})
    projection_as_of = parse_time(status.get("projections_as_of")) or parse_time(status.get("fetched_at"))
    player_history = defaultdict(list)
    for row in history: player_history[row["fpid"]].append(row)

    pending_top = []
    for player in players:
        fpid = str(player.get("fpid") or ""); meta = current_meta.get(fpid, {})
        player["age"] = as_number(meta.get("age"))
        past = sorted(player_history.get(fpid, []), key=lambda x: x["season"])
        prior = [row["games"] for row in past[-2:] if row["games"] is not None]
        prior_games = sum(prior) / len(prior) if prior else None
        matches, cohort_label = cohort(history, player, prior_games)
        residuals = [row["residual"] for row in matches]
        if len(residuals) >= MIN_COHORT:
            q20, q50, q80 = (quantile(residuals, q) for q in (0.2, 0.5, 0.8))
        else:
            q20, q50, q80 = DEFAULT_RANGES.get(player["pos"], (-0.4, 0, 0.2))
        player_events = events_by_player.get(fpid, [])
        if player.get("ecr", 999) <= 300:
            pending_top.extend(e["event_id"] for e in player_events if e.get("review_state") == "pending")
        overlays = [e for e in player_events if active_overlay(e, projection_as_of)]
        factors = [(1.0, 1.0)]; expected_games = 17.0
        if overlays:
            factors = [(1.0, 1.0)]
            for event in overlays:
                combined = []
                for base_factor, base_weight in factors:
                    for scenario in event["scenarios"]:
                        probability = as_number(scenario.get("probability"), 0)
                        games = as_number(scenario.get("games_missed"), 0)
                        performance = as_number(scenario.get("performance_multiplier"), 1)
                        combined.append((base_factor * max(0, (17 - games) / 17) * performance,
                                         base_weight * probability))
                factors = combined
            event_factor = sum(value * weight for value, weight in factors) / sum(weight for _, weight in factors)
            expected_games = max(0, 17 - sum(
                sum(as_number(s.get("probability"), 0) * as_number(s.get("games_missed"), 0)
                    for s in event["scenarios"]) for event in overlays))
        else:
            event_factor = 1.0
        event_p20, event_p80 = weighted_quantile(factors, .2), weighted_quantile(factors, .8)
        by_scoring = {}
        for scoring, market in scorings_for(player, scorings).items():
            if market is None:
                by_scoring[scoring] = {"market": None, "expected": None, "floor": None, "ceiling": None}
                continue
            by_scoring[scoring] = {
                "market": round(market, 1),
                "expected": round(max(0, market * (1 + q50) * event_factor), 1),
                "floor": round(max(0, market * (1 + q20) * event_p20), 1),
                "ceiling": round(max(0, market * (1 + q80) * event_p80), 1),
            }
        std = by_scoring["std"]
        grade_impact = None
        if std["expected"] is not None:
            grade_impact = {
                "early": round(.75 * std["expected"] + .25 * std["floor"] - std["market"], 1),
                "middle": round(std["expected"] - std["market"], 1),
                "late": round(.75 * std["expected"] + .25 * std["ceiling"] - std["market"], 1),
            }
        covered = bool(fpid and (meta or past or player_events or news_by_player.get(fpid)))
        injury = risk_level(prior_games, player_events, "injury") if covered else "unknown"
        legal = risk_level(None, player_events, "legal") if covered else "unknown"
        role = risk_level(None, player_events, "role") if covered else "unknown"
        latest = sorted(news_by_player.get(fpid, []), key=lambda x: x.get("created", ""), reverse=True)[:3]
        reasons = []
        if prior_games is not None and prior_games < 15.5: reasons.append(f"{prior_games:.1f} games/year over the last two seasons")
        reasons.extend(e.get("summary", "") for e in overlays if e.get("summary"))
        player["forecast"] = {
            "as_of": status.get("fetched_at") or str(datetime.now(timezone.utc).date()),
            "projection_as_of": status.get("projections_as_of") or status.get("fetched_at"),
            "by_scoring": by_scoring, "expected_games": round(expected_games, 1),
            "historical_games": round(prior_games, 1) if prior_games is not None else None,
            "injury_risk": injury, "legal_risk": legal, "role_risk": role,
            "availability_risk": max_risk(injury, legal, role),
            "confidence": "high" if len(matches) >= MIN_COHORT and not any(e.get("review_state") == "pending" for e in player_events)
                          else "medium" if len(matches) >= MIN_COHORT else "low",
            "cohort": cohort_label, "cohort_size": len(matches),
            "grade_impact": grade_impact,
            "reasons": reasons[:3], "events": player_events[:5], "latest_news": latest,
        }
    return {"history_seasons": sorted({row["season"] for row in history}), "history_rows": len(history),
            "pending_top_events": sorted(set(pending_top)), "projection_as_of": status.get("projections_as_of")}


def scorings_for(player: dict, scorings: dict[str, float]) -> dict[str, float | None]:
    market = player.get("proj_pts"); rec = player.get("rec") or 0
    if market is None: return {key: None for key in scorings}
    return {key: float(market) + ppr * float(rec) for key, ppr in scorings.items()}
