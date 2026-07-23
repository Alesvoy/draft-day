#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import refresh_data
from review_news import validate_scenarios
from risk_forecast import add_forecasts, validate_events, validate_release_status


FIXTURES = HERE / "fixtures" / "fantasypros"


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.old = refresh_data.ROOT, refresh_data.DATA, refresh_data.CACHE
        refresh_data.ROOT = self.root; refresh_data.DATA = self.root / "data"; refresh_data.CACHE = self.root / ".cache"

    def tearDown(self):
        refresh_data.ROOT, refresh_data.DATA, refresh_data.CACHE = self.old
        self.tmp.cleanup()

    def args(self, fixtures=FIXTURES):
        return argparse.Namespace(season=2026, fixture_dir=fixtures, base_url=refresh_data.API_BASE,
                                  skip_history=True, refresh_history=False, as_of="2026-07-22T13:00:00Z")

    def test_atomic_refresh_normalizes_ids_snapshots_and_events(self):
        self.data = self.root / "data"; self.data.mkdir()
        self.data.joinpath("risk_events.json").write_text(json.dumps([{
            "event_id":"prior-injury","fpid":"103","type":"injury","status":"confirmed",
            "published_at":"2026-07-01T00:00:00Z","review_state":"approved",
            "scenarios":[{"label":"out","probability":1,"games_missed":2,"performance_multiplier":1}]
        }]))
        summary = refresh_data.refresh(self.args())
        self.assertEqual(summary["ranking_count"], 4)
        with (self.root / "data/rankings_std.csv").open() as source:
            ranking = next(csv.DictReader(source))
        self.assertEqual(ranking["fpid"], "101")
        self.assertEqual(ranking["adp_status"], "current")
        with (self.root / "data/rankings_std.csv").open() as source:
            rankings = list(csv.DictReader(source))
        self.assertEqual(next(r for r in rankings if r["fpid"] == "103")["adp_status"], "missing")
        self.assertTrue((self.root / "data/snapshots/2026/20260722T130000Z/projections_std.csv").exists())
        events = json.loads((self.root / "data/risk_events.json").read_text())
        states = {e["event_id"]: e["review_state"] for e in events}
        self.assertEqual(states["fp-news-1"], "approved")
        self.assertEqual(states["fp-news-2"], "pending")
        self.assertEqual(states["fp-news-3"], "display_only")
        self.assertEqual(states["prior-injury"], "display_only")
        self.assertFalse(any(e["fpid"] == "104" for e in events))
        later = self.args(); later.as_of = "2026-07-22T14:00:00Z"; refresh_data.refresh(later)
        self.assertTrue((self.root / "data/snapshots/2026/20260722T140000Z/rankings_std.csv").exists())

    def test_current_five_season_history_is_reused(self):
        data = self.root / "data"; data.mkdir()
        history = "fpid,gsis_id,season,name,pos,age,ecr,projected_std,actual_std,games,attempts,carries,targets\n"
        history += "".join(f"1,,{year},Player,RB,25,10,200,190,16,0,200,30\n" for year in range(2021, 2026))
        (data / "player_history.csv").write_text(history)
        args = self.args(); args.skip_history = False
        refresh_data.refresh(args)
        self.assertEqual((data / "player_history.csv").read_text(), history)

    def test_invalid_payload_does_not_replace_existing_data(self):
        data = self.root / "data"; data.mkdir(); target = data / "rankings_std.csv"; target.write_text("sentinel\n")
        broken = self.root / "broken"; shutil.copytree(FIXTURES, broken)
        payload = json.loads((broken / "rankings.json").read_text()); payload["players"] = payload["players"][:1]
        (broken / "rankings.json").write_text(json.dumps(payload))
        with self.assertRaises(RuntimeError): refresh_data.refresh(self.args(broken))
        self.assertEqual(target.read_text(), "sentinel\n")


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.data = Path(self.tmp.name)
        fields = ["fpid","gsis_id","season","name","pos","age","ecr","projected_std","actual_std","games","attempts","carries","targets"]
        rows = []
        for i in range(36):
            projected = 200; residual = (i % 9 - 4) / 20
            rows.append({"fpid": str(1000+i), "gsis_id": "", "season": 2025, "name": f"RB {i}", "pos": "RB",
                         "age": 26, "ecr": 40, "projected_std": projected, "actual_std": projected*(1+residual),
                         "games": 17 if i % 4 else 12, "attempts": 0, "carries": 200, "targets": 40})
        rows += [
            {"fpid":"2000","gsis_id":"","season":2024,"name":"Current RB","pos":"RB","age":25,"ecr":40,"projected_std":200,"actual_std":80,"games":4,"attempts":0,"carries":50,"targets":15},
            {"fpid":"2000","gsis_id":"","season":2025,"name":"Current RB","pos":"RB","age":26,"ecr":40,"projected_std":200,"actual_std":210,"games":17,"attempts":0,"carries":250,"targets":60},
        ]
        with (self.data / "player_history.csv").open("w", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
        (self.data / "players.json").write_text(json.dumps([{"fpid":"2000","name":"Current RB","age":27}]))
        (self.data / "news_current.json").write_text("[]")
        (self.data / "data_status.json").write_text(json.dumps({"fetched_at":"2026-07-21T12:00:00Z","projections_as_of":"2026-07-21T12:00:00Z"}))

    def tearDown(self): self.tmp.cleanup()

    def player(self):
        return {"fpid":"2000","name":"Current RB","pos":"RB","ecr":40,"proj_pts":200.0,"rec":40.0}

    def test_history_widens_range_without_forcing_absence(self):
        (self.data / "risk_events.json").write_text("[]")
        player = self.player(); add_forecasts([player], self.data, {"std":0,"half":.5,"full":1})
        forecast = player["forecast"]; std = forecast["by_scoring"]["std"]
        self.assertLess(std["floor"], std["expected"]); self.assertGreater(std["ceiling"], std["expected"])
        self.assertEqual(forecast["expected_games"], 17.0)
        self.assertEqual(forecast["injury_risk"], "high")

    def test_missing_live_data_is_unknown_not_low_risk(self):
        (self.data / "players.json").write_text("[]")
        (self.data / "risk_events.json").write_text("[]")
        player = {"fpid":None,"name":"Unknown RB","pos":"RB","ecr":50,"proj_pts":150.0,"rec":20.0}
        add_forecasts([player], self.data, {"std":0,"half":.5,"full":1})
        self.assertEqual(player["forecast"]["availability_risk"], "unknown")

    def test_only_post_projection_approved_event_moves_mean(self):
        base = {"event_id":"old","fpid":"2000","type":"injury","status":"confirmed","review_state":"approved",
                "published_at":"2026-07-20T12:00:00Z","projection_incorporation":"unpriced",
                "scenarios":[{"label":"out","probability":1,"games_missed":4,"performance_multiplier":1}]}
        (self.data / "risk_events.json").write_text(json.dumps([base]))
        old = self.player(); add_forecasts([old], self.data, {"std":0,"half":.5,"full":1})
        old_mean = old["forecast"]["by_scoring"]["std"]["expected"]
        base["event_id"] = "new"; base["published_at"] = "2026-07-22T12:00:00Z"
        (self.data / "risk_events.json").write_text(json.dumps([base]))
        new = self.player(); add_forecasts([new], self.data, {"std":0,"half":.5,"full":1})
        self.assertLess(new["forecast"]["by_scoring"]["std"]["expected"], old_mean)
        self.assertEqual(new["forecast"]["expected_games"], 13.0)

    def test_validation_rejects_bad_probability_and_stale_or_unmapped_data(self):
        with self.assertRaises(ValueError):
            validate_events([{"event_id":"bad","review_state":"approved","scenarios":[{"probability":.7,"games_missed":1,"performance_multiplier":1}]}])
        with self.assertRaises(ValueError): validate_scenarios([{"probability":.5,"games_missed":1,"performance_multiplier":1}])
        with self.assertRaises(ValueError):
            validate_release_status([{"name":"No ID","ecr":1,"fpid":None}], self.data,
                                    now=datetime(2026,7,22,tzinfo=timezone.utc))
        (self.data / "data_status.json").write_text(json.dumps({"fetched_at":"2026-06-01T00:00:00Z"}))
        with self.assertRaises(ValueError):
            validate_release_status([{"name":"Mapped","ecr":1,"fpid":"1"}], self.data,
                                    now=datetime(2026,7,22,tzinfo=timezone.utc))


class ArtifactTests(unittest.TestCase):
    def test_offline_artifacts_contain_no_credentials_or_runtime_api_calls(self):
        for name in ("app_template.html",):
            text = (HERE / name).read_text()
            self.assertNotIn("FANTASYPROS_API_KEY", text)
            self.assertNotIn("x-api-key", text.lower())
            self.assertNotIn("fetch(", text)


if __name__ == "__main__": unittest.main()
