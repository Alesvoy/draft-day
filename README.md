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
| `data/player_history.csv` | Five completed seasons of preseason-vs-actual calibration data. Rebuilt once, then appended annually. |
| `data/risk_events.json` | Reviewed injury, suspension, legal, and role events with explicit outcome scenarios. |
| `data/guide_leans_2026.json` | Late-Round Draft Guide target / avoid / dart calls with conviction (1-10) and a one-line note. Display-only — never touches scoring. |
| `data/player_profiles_2026.json` | The case for each player: situation, pros, cons, bottom line. Powers the expandable rows on study mode's pick cards. |
| `build/refresh_data.py` | Authenticated, atomic refresh for rankings, ADP, projections, metadata, injuries, news, history, and dated snapshots. |
| `build/review_news.py` | Lists and resolves ambiguous news before it can affect a draft grade. |
| `build/build_board.py` | Computes the layer (VOR, tiers, value/ceiling flags, per-config matrices) and writes `board.json`. |
| `build/make_app.py` | Embeds `board.json` into the HTML template → `draft-assistant.html` and the GitHub Pages `index.html`. |
| `build/make_cheatsheet.py` | Renders `cheatsheet.pdf` from `board.json`. |
| `build/app_template.html` | The app's HTML/CSS/JS (edit here, not the generated file). |
| `build/test_parity.mjs` | Runs the app's engine through scripted drafts; compares against `build/golden/` to prove default behavior never drifts. |
| `build/check_board_parity.py` | Verifies a rebuilt `board.json` keeps every legacy field identical to the golden baseline. |

## Study mode

Study mode turns the default 14-team Standard board into a printable one-page
brain sheet and persistent flashcard drills. It is a mobile-first companion app
(designed for iPhone Safari, Add to Home Screen, offline). Build it with:

```
python3 build/make_study.py
```

This writes `study/index.html`, served at
[https://alesvoy.github.io/draft-day/study/](https://alesvoy.github.io/draft-day/study/).
Open `study/index.html` directly for local use — it is self-contained and works offline.

The sheet's **14-pick plan** turns each of your picks into a card: the overall
pick number, the plan sentence, then the players to target and the traps to
refuse *at that pick*, each with the odds he is still on the board (a normal
curve around his ADP) and a tappable case file from
`data/player_profiles_2026.json` + `data/guide_leans_2026.json`, both embedded
at build time. The flashcard deck is untouched by any of it —
`node build/test_study.mjs` proves the availability model and row selection
alongside the existing deck assertions.

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
   - **Forecast range** — empirical 20th/50th/80th-percentile outcomes from five
     completed seasons, with current approved availability events applied only
     when they are newer than the market projection.
   - **Flags** — pick-relative VALUE / REACH plus WIDE-ECR / TIGHT-ECR expert agreement.
4. **Review risk events.** Confirmed missed time is applied automatically. Legal
   allegations, rumors, and unclear recovery timelines require explicit review.
5. **Freeze** to `board.json`. On draft day the app does only two things: cross off
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
- **Player-risk utility:** early picks blend expected value with the historical
  floor, middle picks use expected value, and late picks blend in ceiling. Injury,
  legal, and role risks remain separate from draft-availability risk.
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

## Refreshing and releasing

Request a personal FantasyPros API key, keep it in the environment, and never
commit it. The first refresh backfills five completed seasons; later refreshes
reuse that history.

```
export FANTASYPROS_API_KEY='...'
python3 build/refresh_data.py --season 2026
python3 build/review_news.py --list
```

For each pending item, use `--display-only`, `--resolve`, or approve a JSON file
containing scenarios whose probabilities total 1. Example:

```
[
  {"label":"no missed time","probability":0.7,"games_missed":0,"performance_multiplier":1.0},
  {"label":"four games","probability":0.3,"games_missed":4,"performance_multiplier":1.0}
]

python3 build/review_news.py --event fp-news-123 --approve scenarios.json
```

Then build and verify the offline release:

```
python3 build/build_board.py
python3 build/test_pipeline.py
node build/test_risk.mjs
node build/test_parity.mjs --board board.json --check-scoring
python3 build/make_app.py
python3 build/make_cheatsheet.py
```

The release build stops for data older than 14 days, missing FantasyPros IDs in
the top 300, invalid scenarios, or pending risk events for draftable players.
Raw downloads stay under ignored `.cache/`; compact dated rankings and projections
are saved under `data/snapshots/`. The generated browser app contains no API key
and performs no runtime data requests.

## Tuning beyond the setup screen

League size, scoring, and rounds are set **in the app** at setup. The remaining
knobs live at the top of `build/build_board.py`: `LEAGUE` (starting lineup
shape), `FLEX_SHARE` (how the flex splits RB/WR per scoring — drives the VOR
baselines), `TIER_SENS` (tier granularity), `TEAM_OPTIONS` / `SCORING_OPTIONS`
(what the setup screen offers). Change, re-run, the board and app update. If you
buy the UDK, drop its tiers in as a cross-check — the architecture doesn't change.
