#!/usr/bin/env python3
"""Prove the rebuilt board.json leaves every legacy field byte-identical to the
golden baseline (build/golden/board.baseline.json). New keys must be additive.

    python3 build/check_board_parity.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

new = json.load(open(os.path.join(ROOT, "board.json")))
old = json.load(open(os.path.join(HERE, "golden", "board.baseline.json")))

META_EXEMPT = {"built"}  # build date legitimately changes
errors = []

# --- meta: every legacy key unchanged ---
for k, v in old["meta"].items():
    if k in META_EXEMPT:
        continue
    if k not in new["meta"]:
        errors.append(f"meta.{k} REMOVED")
    elif new["meta"][k] != v:
        errors.append(f"meta.{k} CHANGED: {v!r} -> {new['meta'][k]!r}")

# --- players: same order, every legacy key unchanged ---
if len(new["players"]) != len(old["players"]):
    errors.append(f"player count {len(old['players'])} -> {len(new['players'])}")
for i, (po, pn) in enumerate(zip(old["players"], new["players"])):
    if po["name"] != pn["name"]:
        errors.append(f"players[{i}] order changed: {po['name']} -> {pn['name']}")
        break
    for k, v in po.items():
        if k not in pn:
            errors.append(f"{po['name']}: key {k} REMOVED")
        elif pn[k] != v:
            errors.append(f"{po['name']}.{k} CHANGED: {v!r} -> {pn[k]!r}")

# --- new-key inventory (informational) ---
new_meta_keys = sorted(set(new["meta"]) - set(old["meta"]))
new_player_keys = sorted(set(new["players"][0]) - set(old["players"][0]))
print("additive meta keys:  ", new_meta_keys)
print("additive player keys:", new_player_keys)

if errors:
    print(f"\nBOARD PARITY FAILED ({len(errors)} issues):")
    for e in errors[:40]:
        print(" ", e)
    sys.exit(1)
print("\nBOARD PARITY OK — all legacy fields byte-identical")
