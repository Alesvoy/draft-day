#!/usr/bin/env python3
"""Inject the frozen board.json into the HTML template -> draft-assistant.html
(a single self-contained, fully-offline file for iPhone Safari)."""
import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

board = json.load(open(os.path.join(ROOT, "board.json")))
tpl = open(os.path.join(HERE, "app_template.html")).read()
# compact JSON keeps the file small; embedded so it works from file:// with no network
html = tpl.replace("__BOARD_JSON__", json.dumps(board, separators=(",", ":")))
out = os.path.join(ROOT, "draft-assistant.html")
open(out, "w").write(html)
print("Wrote %s (%d KB)" % (out, len(html) // 1024))
