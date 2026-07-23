#!/usr/bin/env python3
"""Build study.html -- the offline memorization trainer (brain sheet + flashcard
drills) for no-electronics drafts. Same embedding pattern as make_app.py:
board.json is inlined so the page works from file:// with no network."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

board = json.load(open(os.path.join(ROOT, "board.json")))
tpl = open(os.path.join(HERE, "study_template.html")).read()
html = tpl.replace("__BOARD_JSON__", json.dumps(board, separators=(",", ":")))
out_dir = os.path.join(ROOT, "study")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "index.html")
open(out, "w").write(html)
print("Wrote %s (%d KB)" % (out, len(html) // 1024))
