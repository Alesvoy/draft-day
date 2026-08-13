#!/usr/bin/env python3
"""Build study.html -- the offline memorization trainer (brain sheet + flashcard
drills) for no-electronics drafts. Same embedding pattern as make_app.py:
board.json is inlined so the page works from file:// with no network."""
import json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")


def norm_name(name):
    """Same match key build_board.py uses for guide leans."""
    parts = re.sub(r"[^a-z ]", "", name.lower()).split()
    return " ".join(x for x in parts if x not in {"jr", "sr", "ii", "iii", "iv", "v"})


def profiles():
    """The pick-card case files: {name: {situation, pros, cons, bottom_line}},
    with the Late-Round Draft Guide's {stance, cl, note} folded in so the page
    needs one lookup per player. Missing files degrade to no profiles, which
    just empties the target/avoid rows."""
    path = os.path.join(DATA, "player_profiles_2026.json")
    if not os.path.exists(path):
        return {}
    out = json.load(open(path)).get("profiles", {})
    by_key = {norm_name(n): n for n in out}
    leans = os.path.join(DATA, "guide_leans_2026.json")
    if os.path.exists(leans):
        for lean in json.load(open(leans)):
            name = by_key.get(norm_name(lean["name"]))
            if name:
                out[name].update(stance=lean["stance"], cl=lean["cl"], note=lean["note"])
    return out


board = json.load(open(os.path.join(ROOT, "board.json")))
tpl = open(os.path.join(HERE, "study_template.html")).read()
# legacy id->{type,key} map: bootstraps Leitner-progress migration for users from
# before 'study-meta' existed (see study_template.html). Optional -- absence is fine.
legacy_path = os.path.join(HERE, "legacy_study_meta.json")
legacy = open(legacy_path).read().strip() if os.path.exists(legacy_path) else "{}"
html = tpl.replace("__BOARD_JSON__", json.dumps(board, separators=(",", ":")))
html = html.replace("__PROFILES_JSON__", json.dumps(profiles(), separators=(",", ":")))
html = html.replace("__LEGACY_META__", legacy)
out_dir = os.path.join(ROOT, "study")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "index.html")
open(out, "w").write(html)
print("Wrote %s (%d KB)" % (out, len(html) // 1024))
