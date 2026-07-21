#!/usr/bin/env python3
"""Refresh all forward-looking draft inputs and compact historical calibration data.

Live use requires FANTASYPROS_API_KEY. Tests can pass --fixture-dir to read the
same endpoint payloads from local JSON without network access.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / ".cache" / "draft-data"
API_BASE = "https://api.fantasypros.com/public/v2/json"
NFLVERSE_STATS = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv.gz"
PLAYER_IDS = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST"}
RISK_WORDS = re.compile(
    r"\b(injur|surg|rehab|pup|ir\b|out\b|miss(?:es|ed|ing)?\b|suspend|jail|prison|"
    r"arrest|charg|investigat|legal|probation|holdout|retir|released|waived|trade|sign(?:ed|ing)?|"
    r"starter|depth chart|cleared|activated|returns?|suspend(?:ed|sion)?)\b", re.I)
RESOLVED_WORDS = re.compile(r"\b(cleared|activated|returns?|released from (?:jail|prison)|no suspension)\b", re.I)
SUSPENSION_RE = re.compile(r"suspend(?:ed|sion)?\D{0,20}(\d+)\s*games?", re.I)
RESERVE_RE = re.compile(r"\b(?:placed|lands?) on (?:injured reserve|IR|reserve/PUP)\b", re.I)
RULED_OUT_RE = re.compile(r"\bruled out\b", re.I)
SEASON_END_RE = re.compile(r"\b(?:out for the season|season-ending)\b", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def number(value: object, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def rows(payload: object, *keys: str) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


class Source:
    def __init__(self, key: str | None, fixture_dir: Path | None, base_url: str = API_BASE):
        self.key, self.fixture_dir, self.base_url = key, fixture_dir, base_url.rstrip("/")

    def json(self, fixture: str, endpoint: str, params: dict | None = None):
        if self.fixture_dir:
            return json.loads((self.fixture_dir / f"{fixture}.json").read_text())
        if not self.key:
            raise RuntimeError("FANTASYPROS_API_KEY is required (or pass --fixture-dir)")
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        if params:
            url += "?" + urlencode(params)
        request = Request(url, headers={"x-api-key": self.key, "User-Agent": "Fantasy-Draft-Day-Tool/2.0"})
        with urlopen(request, timeout=60) as response:
            return json.load(response)


def fp_id(row: dict) -> str:
    return str(row.get("fpid") or row.get("player_id") or row.get("id") or "").strip()


def normalize_current(source: Source, season: int, fetched_at: str) -> dict[str, object]:
    players_payload = source.json("players", "nfl/players")
    rankings_payload = source.json(
        "rankings", f"nfl/{season}/consensus-rankings",
        {"position": "ALL", "scoring": "STD", "week": 0},
    )
    adp_payload = source.json(
        "adp", f"nfl/{season}/consensus-rankings",
        {"position": "ALL", "scoring": "STD", "week": 0, "type": "ADP"},
    )
    projections_payload = source.json(
        "projections", f"nfl/{season}/projections",
        {"week": 0, "positions": "QB:RB:WR:TE:K:DST", "scoring": "STD"},
    )
    news_payload = source.json("news", "nfl/news", {"limit": 1000})
    try:
        injuries_payload = source.json("injuries", f"nfl/{season}/injuries")
    except Exception:
        injuries_payload = {"injuries": []}

    players = {fp_id(p): p for p in rows(players_payload, "players") if fp_id(p)}
    catalog = [{"fpid": fpid, "birthdate": p.get("birthdate") or "", "age": number(p.get("age"))}
               for fpid, p in players.items()]
    rankings = rows(rankings_payload, "players", "rankings")
    adps = {fp_id(p): number(p.get("rank_ecr") or p.get("rank_adp") or p.get("adp"))
            for p in rows(adp_payload, "players", "rankings") if fp_id(p)}
    projections = {fp_id(p): p for p in rows(projections_payload, "players") if fp_id(p)}
    minimum_rankings = 2 if source.fixture_dir else 100
    minimum_projections = 2 if source.fixture_dir else 80
    if len(rankings) < minimum_rankings:
        raise RuntimeError(f"rankings payload too small: {len(rankings)}")
    if len(projections) < minimum_projections:
        raise RuntimeError(f"projections payload too small: {len(projections)}")

    ranking_rows, projection_rows, split_rows, current_players = [], [], [], []
    for rank in rankings:
        fpid = fp_id(rank)
        pos = str(rank.get("player_position_id") or rank.get("position_id") or rank.get("pos") or "")
        if not fpid or pos not in POSITIONS:
            continue
        meta, proj = players.get(fpid, {}), projections.get(fpid, {})
        stats = proj.get("stats") or {}
        ecr = int(number(rank.get("rank_ecr") or rank.get("ecr"), 0))
        adp = adps.get(fpid) or number(meta.get("rank_adp") or rank.get("rank_adp") or rank.get("adp"))
        if adp is not None:
            adp = int(round(adp))
        delta = "" if adp is None else adp - ecr
        ranking_rows.append({
            "fpid": fpid,
            "name": rank.get("player_name") or rank.get("name"),
            "team": rank.get("player_team_id") or rank.get("team_id") or meta.get("team_id") or "FA",
            "pos": pos,
            "bye": rank.get("player_bye_week") or rank.get("bye") or "",
            "ecr": ecr,
            "adp": "" if adp is None else adp,
            "adp_status": "missing" if adp is None else "current",
            "ecr_vs_adp": "" if adp is None else (f"+{delta}" if delta > 0 else delta),
            "rank_std": f"{number(rank.get('rank_std'), 0):.2f}",
            "fp_tier": int(number(rank.get("tier"), 0)),
            "source_updated_at": fetched_at,
        })
        current_players.append({
            "fpid": fpid,
            "name": ranking_rows[-1]["name"], "team": ranking_rows[-1]["team"], "pos": pos,
            "birthdate": meta.get("birthdate") or "", "age": number(meta.get("age")),
            "sportsdata_id": meta.get("sportsdata_player_id") or meta.get("sportsdata_id") or "",
        })
        if proj:
            points = number(stats.get("points"))
            rec = number(stats.get("rec_rec"), 0)
            projection_rows.append({"fpid": fpid, "name": ranking_rows[-1]["name"], "pos": pos,
                                    "proj_pts": points, "rec": rec, "source_updated_at": fetched_at})
            split_rows.append({
                "fpid": fpid, "name": ranking_rows[-1]["name"],
                "rec_yds": number(stats.get("rec_yds")), "rec_td": number(stats.get("rec_tds")),
                "rush_yds": number(stats.get("rush_yds")), "rush_td": number(stats.get("rush_tds")),
            })

    known = {r["fpid"] for r in ranking_rows}
    missing = [r for r in ranking_rows if r["ecr"] <= 300 and r["fpid"] not in projections]
    if len(missing) > 75:
        raise RuntimeError(f"too many top-300 players lack projections: {len(missing)}")

    news = []
    for item in rows(news_payload, "items", "news"):
        fpid = fp_id(item)
        if not fpid:
            title = clean_text(item.get("title"))
            matches = [p for p in current_players if title.lower().startswith(str(p["name"]).lower())]
            fpid = matches[0]["fpid"] if len(matches) == 1 else ""
        if fpid and fpid not in known:
            continue
        news.append({
            "id": str(item.get("id") or hashlib.sha1(str(item).encode()).hexdigest()[:12]),
            "fpid": fpid, "created": item.get("created") or item.get("published_at") or fetched_at,
            "category": item.get("category") or "", "title": clean_text(item.get("title")),
            "summary": clean_text(item.get("desc") or item.get("description"))[:500],
            "link": item.get("link") or item.get("url") or "",
        })
    injuries = []
    for item in rows(injuries_payload, "injuries", "players", "items"):
        fpid = fp_id(item)
        if fpid and fpid in known:
            injuries.append({
                "fpid": fpid, "status": item.get("status") or item.get("game_status") or "",
                "injury": item.get("injury") or item.get("body_part") or "",
                "practice": item.get("practice_status") or "",
                "updated_at": item.get("updated_at") or item.get("report_date") or fetched_at,
            })
    return {
        "rankings": ranking_rows, "projections": projection_rows, "splits": split_rows,
        "players": current_players, "catalog": catalog, "news": news, "injuries": injuries,
        "status": {
            "season": season, "fetched_at": fetched_at,
            "rankings_as_of": rankings_payload.get("last_updated") or fetched_at,
            "projections_as_of": projections_payload.get("last_updated") or fetched_at,
            "ranking_count": len(ranking_rows), "projection_count": len(projection_rows),
            "news_count": len(news), "injury_count": len(injuries),
        },
    }


def merge_events(existing: list[dict], news: list[dict], injuries: list[dict], fetched_at: str) -> list[dict]:
    by_id = {str(e["event_id"]): e for e in existing}
    for item in news:
        text = f"{item['title']} {item['summary']}"
        if not item["fpid"] or not RISK_WORDS.search(text):
            continue
        event_id = f"fp-news-{item['id']}"
        if event_id in by_id:
            continue
        resolved = bool(RESOLVED_WORDS.search(text))
        suspension = SUSPENSION_RE.search(text)
        reserve, ruled_out, season_end = RESERVE_RE.search(text), RULED_OUT_RE.search(text), SEASON_END_RE.search(text)
        auto = bool(suspension or reserve or ruled_out or season_end) and not resolved
        games = int(suspension.group(1)) if suspension else 17 if season_end else 4 if reserve else 1 if ruled_out else 0
        event_type = ("legal" if re.search(r"arrest|charg|jail|prison|legal|probation", text, re.I)
                      else "suspension" if "suspend" in text.lower()
                      else "role" if re.search(r"trade|sign|release|waiv|holdout|retir|starter|depth chart", text, re.I)
                      else "injury")
        by_id[event_id] = {
            "event_id": event_id, "fpid": item["fpid"],
            "type": event_type,
            "status": "resolved" if resolved else "confirmed" if auto else "reported",
            "published_at": item["created"], "verified_at": fetched_at,
            "source_url": item["link"], "summary": item["title"],
            "review_state": "display_only" if resolved else "approved" if auto else "pending",
            "expires_at": "", "projection_incorporation": "unpriced",
            "scenarios": ([{"label": "confirmed", "probability": 1.0,
                             "games_missed": games, "performance_multiplier": 1.0}] if auto else []),
        }
    for injury in injuries:
        status = str(injury["status"]).lower()
        if not any(word in status for word in ("out", "reserve", "pup", "suspend")):
            continue
        digest = hashlib.sha1(f"{injury['fpid']}:{injury['status']}:{injury['injury']}".encode()).hexdigest()[:12]
        event_id = f"fp-injury-{digest}"
        if event_id not in by_id:
            by_id[event_id] = {
                "event_id": event_id, "fpid": injury["fpid"], "type": "injury", "status": "confirmed",
                "published_at": injury["updated_at"], "verified_at": fetched_at, "source_url": "",
                "summary": f"{injury['status']}: {injury['injury']}".strip(": "),
                "review_state": "approved", "expires_at": "", "projection_incorporation": "unpriced",
                "scenarios": [{"label": "confirmed", "probability": 1.0,
                               "games_missed": 4 if any(x in status for x in ("reserve", "pup")) else 1,
                               "performance_multiplier": 1.0}],
            }
    events = list(by_id.values())
    for resolved in [e for e in events if e.get("status") == "resolved"]:
        for prior in events:
            if (prior["event_id"] != resolved["event_id"] and prior.get("fpid") == resolved.get("fpid")
                    and prior.get("type") == resolved.get("type") and prior.get("status") != "resolved"
                    and prior.get("published_at", "") <= resolved.get("published_at", "")):
                prior.update(status="resolved", review_state="display_only", scenarios=[])
    return sorted(events, key=lambda e: (e.get("published_at", ""), e["event_id"]), reverse=True)


def download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Fantasy-Draft-Day-Tool/2.0"})
    with urlopen(request, timeout=120) as response:
        return response.read()


def historical_data(source: Source, season: int, current_players: list[dict], years: int = 5) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    stats_path, ids_path = CACHE / "player_stats.csv.gz", CACHE / "db_playerids.csv"
    if source.fixture_dir:
        stats_path = source.fixture_dir / "player_stats.csv.gz"
        ids_path = source.fixture_dir / "player_ids.csv"
    else:
        if not stats_path.exists(): stats_path.write_bytes(download_bytes(NFLVERSE_STATS))
        if not ids_path.exists(): ids_path.write_bytes(download_bytes(PLAYER_IDS))
    with ids_path.open(newline="") as f:
        crosswalk = {str(r.get("fantasypros_id", "")): r.get("gsis_id", "") for r in csv.DictReader(f)}
    by_gsis_season = defaultdict(lambda: {"weeks": set(), "attempts": 0.0, "carries": 0.0, "targets": 0.0})
    opener = gzip.open if str(stats_path).endswith(".gz") else open
    with opener(stats_path, "rt", newline="") as f:
        for row in csv.DictReader(f):
            y = int(number(row.get("season"), 0))
            if y < season - years or y >= season or row.get("season_type") != "REG": continue
            key = (row.get("player_id", ""), y); agg = by_gsis_season[key]
            agg["weeks"].add(row.get("week"))
            for field in ("attempts", "carries", "targets"):
                agg[field] += number(row.get(field), 0)
    birthdates = {p["fpid"]: p.get("birthdate") for p in current_players}
    result = []
    for year in range(season - years, season):
        projections = source.json(f"history_projections_{year}", f"nfl/{year}/projections",
                                  {"week": 0, "positions": "QB:RB:WR:TE", "scoring": "STD"})
        actuals = source.json(f"history_actuals_{year}", f"nfl/{year}/player-points",
                              {"scoring": "STD"})
        rankings = source.json(f"history_rankings_{year}", f"nfl/{year}/consensus-rankings",
                               {"position": "ALL", "scoring": "STD", "week": 0})
        actual_by_id = {fp_id(x): x for x in rows(actuals, "players") if fp_id(x)}
        ecr_by_id = {fp_id(x): int(number(x.get("rank_ecr") or x.get("ecr"), 999))
                     for x in rows(rankings, "players", "rankings") if fp_id(x)}
        for p in rows(projections, "players"):
            fpid = fp_id(p); actual = actual_by_id.get(fpid)
            stats = p.get("stats") or {}; projected = number(stats.get("points"))
            if not fpid or not actual or projected is None or projected <= 0: continue
            gsis = crosswalk.get(fpid, ""); workload = by_gsis_season[(gsis, year)]
            birth = birthdates.get(fpid); age = None
            if birth:
                try: age = year - date.fromisoformat(str(birth)[:10]).year
                except ValueError: pass
            result.append({
                "fpid": fpid, "gsis_id": gsis, "season": year,
                "name": p.get("name") or actual.get("player_name"),
                "pos": p.get("position_id") or actual.get("position_id"), "age": age,
                "ecr": ecr_by_id.get(fpid, 999), "projected_std": round(projected, 2),
                "actual_std": round(number(actual.get("points"), 0), 2),
                "games": int(number(actual.get("games"), len(workload["weeks"]))),
                "attempts": round(workload["attempts"], 1), "carries": round(workload["carries"], 1),
                "targets": round(workload["targets"], 1),
            })
    return result


def csv_text(data: list[dict], fields: list[str]) -> str:
    out = io.StringIO(newline=""); writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader(); writer.writerows([{k: row.get(k, "") for k in fields} for row in data])
    return out.getvalue()


def atomic_write(outputs: dict[Path, str]) -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="draft-refresh-", dir=ROOT))
    try:
        staged = []
        for target, content in outputs.items():
            relative = target.relative_to(ROOT); temp = temp_root / relative
            temp.parent.mkdir(parents=True, exist_ok=True); temp.write_text(content)
            staged.append((temp, target))
        for temp, target in staged:
            target.parent.mkdir(parents=True, exist_ok=True); os.replace(temp, target)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def refresh(args) -> dict:
    fetched_at = args.as_of or utc_now()
    source = Source(os.environ.get("FANTASYPROS_API_KEY"), args.fixture_dir, args.base_url)
    current = normalize_current(source, args.season, fetched_at)
    events_path = DATA / "risk_events.json"
    existing = json.loads(events_path.read_text()) if events_path.exists() else []
    events = merge_events(existing, current["news"], current["injuries"], fetched_at)
    history_path = DATA / "player_history.csv"
    existing_history = history_path.read_text() if history_path.exists() else ""
    existing_seasons = set()
    if existing_history.strip():
        existing_seasons = {int(row["season"]) for row in csv.DictReader(io.StringIO(existing_history)) if row.get("season")}
    history_is_current = (args.season - 1) in existing_seasons and len(existing_seasons) >= 5
    if args.skip_history and history_path.exists():
        history_text = history_path.read_text()
    elif args.skip_history:
        history_text = csv_text([], ["fpid","gsis_id","season","name","pos","age","ecr","projected_std",
                                     "actual_std","games","attempts","carries","targets"])
    elif history_is_current and not getattr(args, "refresh_history", False):
        history_text = existing_history
    else:
        history = historical_data(source, args.season, current["catalog"])
        history_text = csv_text(history, ["fpid","gsis_id","season","name","pos","age","ecr","projected_std",
                                          "actual_std","games","attempts","carries","targets"])
    stamp = re.sub(r"[^0-9TZ]", "", fetched_at.replace("+00:00", "Z"))[:16]
    outputs = {
        DATA / "rankings_std.csv": csv_text(current["rankings"], list(current["rankings"][0])),
        DATA / "projections_std.csv": csv_text(current["projections"], list(current["projections"][0])),
        DATA / "proj_splits.csv": csv_text(current["splits"], list(current["splits"][0])),
        DATA / "players.json": json.dumps(current["players"], indent=2) + "\n",
        DATA / "news_current.json": json.dumps(current["news"], indent=2) + "\n",
        DATA / "injuries_current.json": json.dumps(current["injuries"], indent=2) + "\n",
        DATA / "risk_events.json": json.dumps(events, indent=2) + "\n",
        DATA / "data_status.json": json.dumps(current["status"], indent=2) + "\n",
        DATA / "player_history.csv": history_text,
        DATA / "snapshots" / str(args.season) / stamp / "rankings_std.csv":
            csv_text(current["rankings"], list(current["rankings"][0])),
        DATA / "snapshots" / str(args.season) / stamp / "projections_std.csv":
            csv_text(current["projections"], list(current["projections"][0])),
    }
    atomic_write(outputs)
    return {**current["status"], "event_count": len(events),
            "pending_events": sum(e.get("review_state") == "pending" for e in events)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=date.today().year)
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--base-url", default=API_BASE)
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--refresh-history", action="store_true", help="force the five-season historical rebuild")
    parser.add_argument("--as-of", help="UTC ISO timestamp, primarily for deterministic tests")
    args = parser.parse_args()
    try:
        summary = refresh(args)
        print(json.dumps(summary, indent=2))
    except Exception as error:
        raise SystemExit(f"ERROR: {error}")


if __name__ == "__main__":
    main()
