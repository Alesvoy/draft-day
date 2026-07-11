# Fantasy Draft Day Tool — 14-team Standard (0 PPR)

An offline draft assistant for an **in-person** draft. The hard analysis is done
**once, before** the draft and frozen into a single source of truth; on draft day
the app only crosses off players and reads the frozen numbers — so it can't
contradict itself.

## What's here

| File | What it is |
|------|-----------|
| `draft-assistant.html` | **The thing you use on draft day.** Single self-contained file, runs fully offline in your iPhone browser. Open it, add to Home Screen, done. |
| `cheatsheet.pdf` | Printable analog backup of the tiered board. Paper never crashes. |
| `board.json` | The frozen board — the single source of truth the app reads. |
| `data/rankings_std.csv` | Raw pull: FantasyPros consensus rankings + ADP (Standard). |
| `data/projections_std.csv` | Raw pull: FantasyPros projected points (Standard). |
| `build/build_board.py` | Computes the layer (VOR, tiers, value/ceiling flags) and writes `board.json`. |
| `build/make_app.py` | Embeds `board.json` into the HTML template → `draft-assistant.html`. |
| `build/make_cheatsheet.py` | Renders `cheatsheet.pdf` from `board.json`. |
| `build/app_template.html` | The app's HTML/CSS/JS (edit here, not the generated file). |

## How it works (design)

1. **Ingest** consensus rankings + ADP (FantasyPros, Standard). This is the FIXED
   order — we never re-rank players ourselves.
2. **Join** Standard projected points onto each player.
3. **Compute a layer on top** — deterministically, in code:
   - **VOR** = projected points above your league's replacement level. Replacement
     ranks are set for 14-team 0-PPR (RB 37, WR 34, QB/TE 14), which is *why*
     elite RBs dominate value in this format.
   - **Value vs ADP** — where experts rank a player vs where the crowd drafts him.
   - **Tiers** — natural breaks (gaps) in the projection curve, per position and
     cross-positionally via VOR.
   - **Flags** — VALUE / REACH / CEILING / SAFE from value-vs-ADP and rank spread.
4. **Freeze** to `board.json`. On draft day the app does only two things: cross off
   who's gone, and recommend the best pick for your roster by reading those frozen
   columns + deterministic roster logic (need × scarcity × value × round).

The recommendation engine respects open starting slots: it leads with scarce RBs
early, but pivots to WR/QB/TE the moment those starters are open — without blindly
chasing need over a clearly elite faller.

## Using it on draft day (iPhone)

1. AirDrop / email `draft-assistant.html` to your phone, open in Safari.
2. Share → **Add to Home Screen** (now it opens full-screen, fully offline).
3. **Set your draft seat** (1–14) when prompted — you'll know it a few minutes
   before the draft. The app uses it to run the snake math.
4. **Log every pick in order, one tap.** Tap the player who was just called — the
   app assigns him to whichever team is on the clock (snake order) and advances.
   When it's your turn the header shows **● YOUR PICK** and the button becomes
   **＋ My Pick**. One button, always means "this player was just taken."
5. The **Recommend** tab shows your best picks with reasoning; **↶ Undo** reverts
   the last pick if you mis-tap. State persists if Safari reloads.

### What the recommendation engine does

- **Tracks all 14 rosters** from the picks you log (snake order), so it knows
  every team's holes — not just yours.
- **Wait-cost:** for each player it estimates the chance he's gone before your
  *next* pick (ADP + how many teams pick in between) and down-weights guys who'll
  still be there, boosting the ones who won't (**NOW** tag). It won't tell you to
  spend a pick on someone you can safely wait on.
- **Positional pressure:** if the teams picking before your next turn are short at
  a position, it treats that position's players as more likely gone — so a run on
  RB makes RB more urgent (the **Lean** banner calls this out).
- **JJ's strategy baked into the math** (not just shown as text): elite-TE-or-wait
  (dead-zone TEs are suppressed mid-draft), Konami QBs favored over pocket passers,
  pass-catching and committee RBs boosted, anchor-a-RB-first. Tags: REC-BACK,
  COMMITTEE, KONAMI, POCKET, ELITE-TE.

It never overrides a clearly elite faller just to fill a need — the tilts are soft.

## Refreshing the data (closer to your draft)

Rankings/ADP/projections move all summer. To refresh:

1. Re-pull the two CSVs in `data/` from FantasyPros (Standard scoring): the
   consensus cheatsheet for `rankings_std.csv`, the QB/RB/WR/TE projection pages
   for `projections_std.csv`. Keep the same columns.
2. Re-run the build:
   ```
   python3 build/build_board.py        # -> board.json
   python3 build/make_app.py           # -> draft-assistant.html
   python3 build/make_cheatsheet.py    # -> cheatsheet.pdf   (needs: pip install reportlab)
   ```
3. Re-send the HTML to your phone.

## Tuning for your exact league

Everything league-specific lives at the top of `build/build_board.py`:
`LEAGUE` (roster slots), `REPLACEMENT_RANK` (drives VOR), `TIER_SENS` (tier
granularity). Change, re-run, the board and app update. If you buy the UDK, drop
its tiers in as a cross-check — the architecture doesn't change.
