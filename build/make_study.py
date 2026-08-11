#!/usr/bin/env python3
"""Build study.html -- the offline memorization trainer (brain sheet + flashcard
drills) for no-electronics drafts. Same embedding pattern as make_app.py:
board.json is inlined so the page works from file:// with no network."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

board = json.load(open(os.path.join(ROOT, "board.json")))
tpl = open(os.path.join(HERE, "study_template.html")).read()
# legacy id->{type,key} map: bootstraps Leitner-progress migration for users from
# before 'study-meta' existed (see study_template.html). Optional -- absence is fine.
legacy_path = os.path.join(HERE, "legacy_study_meta.json")
legacy = open(legacy_path).read().strip() if os.path.exists(legacy_path) else "{}"
html = tpl.replace("__BOARD_JSON__", json.dumps(board, separators=(",", ":")))
html = html.replace("__LEGACY_META__", legacy)
out_dir = os.path.join(ROOT, "study")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "index.html")
open(out, "w").write(html)
print("Wrote %s (%d KB)" % (out, len(html) // 1024))
