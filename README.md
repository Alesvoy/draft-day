# Fantasy Draft Day Tool

An offline draft assistant for an **in-person** draft. The hard analysis is done
**once, before** the draft and frozen into a single source of truth; on draft day
the app only crosses off players and reads the frozen numbers — so it can't
contradict itself.

**League-configurable:** at setup (or after a reset) you pick **teams
(8/10/12/14/16), scoring (Standard / Half PPR / Full PPR), and roster spots per
team** — the value engine (VOR baselines, tiers, flex lean, round gates) adjusts
to the config. Defaults to 14-team Standard, 18 rounds.

## What's here

| File | What it is |
|------|-----------|
| `draft-assistant.html` | **The thing you use on draft day.** Single self-contained file, runs fully offline in your iPhone browser. Open it, add to Home Screen, done. |
| `index.html` | Generated copy of the app served at [alesvoy.github.io/draft-day](https://alesvoy.github.io/draft-day/). |
| `cheatsheet.pdf` | Printable analog backup of the tiered board. Paper never crashes. **Rendered at the default config (14-team Standard)** — the app handles other configs live. |
| `board.json` | The frozen board — the single source of truth the app reads. Carries a value layer for every (scoring × team-count) combo. |
| `data/rankings_std.csv` | Raw pull: FantasyPros consensus rankings + ADP (Standard). |
| `data/projections_std.csv` | Raw pull: FantasyPros projected points (Standard) **+ a `rec` column** (projected receptions — powers the PPR formats). |
| `build/build_board.py` | Computes the layer (VOR, tiers, value/ceiling flags, per-config matrices) and writes `board.json`. |
| `build/make_app.py` | Embeds `board.json` into the HTML template → `draft-assistant.html` and the GitHub Pages `index.html`. |
| `build/make_cheatsheet.py` | Renders `cheatsheet.pdf` from `board.json`. |
| `build/app_template.html` | The app's HTML/CSS/JS (edit here, not the generated file). |
| `build/test_parity.mjs` | Runs the app's engine through scripted drafts; compares against `build/golden/` to prove default behavior never drifts. |
| `build/check_board_parity.py` | Verifies a rebuilt `board.json` keeps every legacy field identical to the golden baseline. |

## How it works (design)

1. **Ingest** consensus rankings + ADP (FantasyPros, Standard). This is the FIXED
   order — we never re-rank players ourselves, and it stays a single Standard
   spine for all scoring formats (per the Late-Round guide: scoring barely moves
   top-player ranks; lineup structure is what moves value).
2. **Join** Standard projected points + projected receptions onto each player.
   PPR is exact math on top: half = +0.5/rec, full = +1/rec.
3. **Compute a layer on top** — deterministically, in code, for every league
   config the setup screen offers:
   - **VOR** = projected points above the replacement level. Replacement ranks
     are **derived from teams × starters + a scoring-dependent share of the flex
     slots** (standard leans the flex RB, full PPR flips it toward WR). At
     14-team standard that lands on the classic RB 37 / WR 34 / QB/TE 14.
   - **Value vs ADP** — where experts rank a player vs where the crowd drafts him.
   - **Tiers** — natural breaks (gaps) in the projection curve, per position and
     cross-positionally via VOR, recomputed per scoring/team-count.
   - **Flags** — VALUE / REACH / CEILING / SAFE from value-vs-ADP and rank spread.
4. **Freeze** to `board.json`. On draft day the app does only two things: cross off
   who's gone, and recommend the best pick for your roster by reading the frozen
   columns for **your** league config + deterministic roster logic
   (need × scarcity × value × round).

The recommendation engine respects open starting slots: it leads with scarce RBs
early, but pivots to WR/QB/TE the moment those starters are open — without blindly
chasing need over a clearly elite faller.

## Using it on draft day (iPhone)

1. AirDrop / email `draft-assistant.html` to your phone, open in Safari.
2. Share → **Add to Home Screen** (now it opens full-screen, fully offline).
3. **League setup** appears on first launch: pick teams, scoring, rounds, then
   tap your draft seat. (Tap the seat pill later to change any of it — that
   clears logged picks, since the snake math depends on the config.)
4. **Log every pick in order, one tap.** Tap the player who was just called — the
   app assigns him to whichever team is on the clock (snake order) and advances.
   When it's your turn the header shows **● YOUR PICK** and the button becomes
   **＋ My Pick**. One button, always means "this player was just taken."
5. The **Recommend** tab shows your best picks with reasoning; **↶ Undo** reverts
   the last pick if you mis-tap. State persists if Safari reloads.

### What the recommendation engine does

- **Tracks every roster** from the picks you log (snake order), so it knows
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
- **Scoring-aware tilts:** pass-catching backs get a bigger boost in half/full
  PPR, the flex lean shifts toward WR in full PPR (also baked into the VOR
  baselines), and the anchor-RB nudge is dropped in full PPR where Zero-RB
  starts are viable. In PPR modes the app notes that ADP/ECR are
  standard-market. K/DST and TE-dead-zone round gates scale with roster size.

It never overrides a clearly elite faller just to fill a need — the tilts are soft.

## Refreshing the data (closer to your draft)

Rankings/ADP/projections move all summer. To refresh:

1. Refresh `rankings_std.csv` with the checked-in FantasyPros importer:
   ```
   python3 build/refresh_rankings.py
   ```
   It verifies that FantasyPros returned **2026 Standard** consensus rankings,
   pulls the full ECR board, applies FantasyPros' current ECR-vs-ADP values
   where published, and retains the prior ADP value where FantasyPros fences
   its aggregate ADP export.
   Re-pull `projections_std.csv` from the QB/RB/WR/TE projection pages. Keep
   the same columns — including **`rec`**
   (projected receptions, the REC column on FantasyPros' projection pages).
   Without a `rec` column the board still builds, but the app disables the
   Half/Full PPR options.
2. Re-run the build:
   ```
   python3 build/build_board.py        # -> board.json
   python3 build/check_board_parity.py # optional: prove legacy fields unchanged
   python3 build/make_app.py           # -> draft-assistant.html + index.html
   python3 build/make_cheatsheet.py    # -> cheatsheet.pdf   (needs: pip install reportlab)
   ```
   (After a data refresh the parity check will legitimately fail — the goldens in
   `build/golden/` describe the old data. Re-capture them:
   `cp board.json build/golden/board.baseline.json &&
   node build/test_parity.mjs --board board.json --out build/golden/engine.baseline.json`.)
3. Re-send the HTML to your phone.

## Tuning beyond the setup screen

League size, scoring, and rounds are set **in the app** at setup. The remaining
knobs live at the top of `build/build_board.py`: `LEAGUE` (starting lineup
shape), `FLEX_SHARE` (how the flex splits RB/WR per scoring — drives the VOR
baselines), `TIER_SENS` (tier granularity), `TEAM_OPTIONS` / `SCORING_OPTIONS`
(what the setup screen offers). Change, re-run, the board and app update. If you
buy the UDK, drop its tiers in as a cross-check — the architecture doesn't change.
