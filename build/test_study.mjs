#!/usr/bin/env node
// Deck harness: runs study_template.html's real card generator against a board
// and reports composition. Proves the banding/cliff rules do what they claim
// instead of trusting a reimplementation.
//
//   node build/test_study.mjs                       # summary
//   node build/test_study.mjs --list Boundary       # every card of one type
//   node build/test_study.mjs --ids                 # id-stability fingerprint
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i >= 0 ? (process.argv[i + 1] ?? true) : d; };

const BOARD = JSON.parse(fs.readFileSync(path.resolve(ROOT, arg('board', 'board.json')), 'utf8'));
const tpl = fs.readFileSync(path.join(HERE, 'study_template.html'), 'utf8');
// the page has two script blocks; the first holds all the logic, the second is boot glue
const script = tpl.slice(tpl.indexOf('<script>') + 8, tpl.indexOf('</script>'));
// drop the two DOM-bound statements at the tail; everything above is pure logic
const logic = script.slice(0, script.indexOf("document.addEventListener('keydown'"));

// PROFILES as make_study.py builds it: the raw case files plus the guide lean.
// build_board.py already merged the leans onto the players under the same
// normalization, so joining on p.lrdg here is the same merge by another door.
const PROFILES = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/player_profiles_2026.json'), 'utf8')).profiles;
for (const p of BOARD.players) if (p.lrdg && PROFILES[p.name]) Object.assign(PROFILES[p.name], p.lrdg);

const store = new Map();
const localStorage = {
  getItem: k => store.has(k) ? store.get(k) : null,
  setItem: (k, v) => store.set(k, String(v)),
};
const make = new Function('BOARD', 'PROF', 'localStorage', 'location', 'document', 'LEGACY',
  logic.replace('const BOARD=__BOARD_JSON__;', '').replace('const PROFILES=__PROFILES_JSON__;', 'const PROFILES=PROF;')
    .replace('const LEGACY_META=__LEGACY_META__;', 'const LEGACY_META=LEGACY;') +
  '\nreturn {cards,card,migrate,TIERS,POSITIONS,bandOf,isCliff,BAND_A_END,BAND_B_END,CLIFF,draftable,' +
  'pAvail,pct5,stampFor,planRows,PROFILES,MAX_TARGETS,MAX_AVOIDS,overall,TEAMS,ROUNDS};');
const S = make(BOARD, PROFILES, localStorage, { hash: '' }, { querySelector: () => null }, {});

const deck = S.cards();
const byType = {};
for (const c of deck) byType[c.type] = (byType[c.type] || 0) + 1;

if (arg('list')) {
  for (const c of deck.filter(c => c.type === arg('list'))) console.log(`  ${c.question}\n     -> ${c.answer}`);
  process.exit(0);
}
if (arg('ids')) {
  for (const c of deck) console.log(`${c.id}\t${c.type}\t${c.question}`);
  process.exit(0);
}

const named = new Set();
for (const pos of S.POSITIONS)
  for (const t of S.TIERS[pos])
    if (t.tier !== 'late' && S.bandOf(t) !== 'C') t.players.forEach(p => named.add(p.name));

console.log(`DECK  ${deck.length} cards   (${S.CLIFF.size} swept every session as cliffs)`);
for (const [t, n] of Object.entries(byType).sort((a, b) => b[1] - a[1])) console.log(`   ${String(n).padStart(4)}  ${t}`);
console.log(`\nnamed players carried: ${named.size}`);
const bands = { A: 0, B: 0, C: 0 };
for (const pos of S.POSITIONS)
  for (const t of S.TIERS[pos]) if (t.tier !== 'late') bands[S.bandOf(t)] += t.players.length;
console.log(`tier players by band:  A ${bands.A}   B ${bands.B}   C ${bands.C} (no cards)`);

const dupes = deck.length - new Set(deck.map(c => c.id)).size;
console.log(`duplicate ids: ${dupes}${dupes ? '   <-- COLLISION' : ''}`);
const noTierNum = deck.every(c => !/tier-\d|tier \d/.test(c.id));
console.log(`ids free of tier ordinals: ${noTierNum}`);
// an unknown type makes prio[type] undefined -> NaN comparator -> silently
// unstable drill order, which looks like randomness rather than a bug
const prio = Object.keys(JSON.parse(fs.readFileSync(path.join(HERE, 'study_template.html'), 'utf8')
  .match(/const prio=(\{[^}]*\})/)[1].replace(/'/g, '"')));
const unknown = [...new Set(deck.map(c => c.type))].filter(t => !prio.includes(t));
console.log(`card types missing from drill priority: ${unknown.length ? unknown.join(', ') + '   <-- FIX' : 'none'}`);

// --- pick cards: availability model + row selection ---
// The deck is untouched by these, but the brain sheet's 14 cards are generated
// from them, so a bad threshold silently prints the wrong names on draft night.
const leans = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/guide_leans_2026.json'), 'utf8'));
const withStance = Object.values(PROFILES).filter(p => p.stance).length;
const picks = [1, 14, 29, 56, 84, 112, 140, 169, 196];
const mono = [8, 30, 60, 120, 999].every(adp =>
  picks.every((n, i) => i === 0 || S.pAvail(adp, n) <= S.pAvail(adp, picks[i - 1]) + 1e-12));
const widens = picks.every(n => S.pAvail(60, n) >= S.pAvail(20, n)); // a later ADP is never less available
const bounded = picks.every(n => [1, 50, 200].every(a => S.pAvail(a, n) >= 0 && S.pAvail(a, n) <= 1));
// the draft's left edge: nobody is gone before the 1.01, whatever his ADP
const anchored = [1.6, 8, 30, 120].every(a => Math.abs(S.pAvail(a, 1) - 1) < 1e-9);
// mid-draft, a player at his own ADP is a coin flip -- half a slot of
// truncation skew is expected and harmless, so this is a band, not a point
const atAdp = [30, 50, 120].every(a => Math.abs(S.pAvail(a, a) - 0.5) < 0.06);
const stampBands = [[100, 'THERE'], [85, 'THERE'], [80, 'LIKELY'], [60, 'LIKELY'], [55, 'COIN FLIP'],
  [35, 'COIN FLIP'], [30, 'IF HE SLIDES'], [0, 'IF HE SLIDES']].every(([v, s]) => S.stampFor(50, v) === s);
const free = S.stampFor(null, S.pct5(S.pAvail(null, 1))) === 'FREE';
const rounded = [0.844, 0.856].map(v => S.pct5(v)).join() === '85,85';  // one rounding feeds bar, % and stamp

let capFail = 0, orphanRow = null, floorFail = 0, emptyCards = 0, freeRows = 0;
for (let seat = 1; seat <= S.TEAMS; seat++)
  for (let round = 1; round <= S.ROUNDS; round++) {
    const pick = S.overall(round, seat), r = S.planRows(pick, round);
    if (r.targets.length > S.MAX_TARGETS || r.avoids.length > S.MAX_AVOIDS) capFail++;
    if (!r.targets.length) emptyCards++;
    for (const p of r.targets) {
      if (!PROFILES[p.name]) orphanRow = p.name;
      if (S.pAvail(p.adp, pick) < 0.12) floorFail++;
      if (!p.adp) freeRows++;
    }
    for (const p of r.avoids) {
      if (!PROFILES[p.name]) orphanRow = p.name;
      const m = p.adp || p.ecr;   // a trap you can fall for: his price sits at or just behind your pick
      if (S.pAvail(p.adp, pick) < 0.25 || !(p.context || []).includes('LRDG-AVOID')) floorFail++;
      if (m < pick - 14 || m > pick + 6) floorFail++;
    }
  }
const rowChecks = [
  // a pre-leans golden board carries no p.lrdg, so there is nothing to merge
  [`profiles carry every guide lean (${withStance}/${leans.length})`,
    !BOARD.players.some(p => p.lrdg) || withStance === leans.length],
  ['pAvail falls as the pick gets later', mono],
  ['pAvail rises with ADP at a fixed pick', widens],
  ['pAvail stays in [0,1]', bounded],
  ['pAvail is 100% at pick 1 for everyone', anchored],
  ['pAvail is ~50% at a player\'s own ADP', atAdp],
  ['stamp bands match their thresholds', stampBands],
  ['no-ADP players stamp FREE', free],
  ['display % rounds to 5s once', rounded],
  [`row caps hold across ${S.TEAMS * S.ROUNDS} cards`, capFail === 0],
  ['every rendered name has a profile', orphanRow === null],
  ['rows respect their availability floors', floorFail === 0],
  ['every card offers at least one target', emptyCards === 0],
  [`late darts render (${freeRows} FREE rows)`, freeRows > 0],
];
let rowFail = 0;
console.log('');
for (const [name, ok] of rowChecks) { if (!ok) rowFail++; console.log(`pick cards: ${name}: ${ok ? 'ok' : 'FAIL'}`); }
if (orphanRow) console.log(`   first name without a profile: ${orphanRow}`);
console.log('');

// --- Leitner-box migration across data refreshes ---
// Old state has boxes for an old deck; the refreshed deck changes some facts.
// Overlapping facts must inherit their box; genuinely new facts must not.
const mk = (type, key) => S.card(type, 'q', 'a', key);
const oldDeck = [
  mk('Tier recall', 'recall|RB|A One, B Two, C Three, D Four, E Five'),
  mk('Tier recall', 'recall|WR|A One, B Two, C Three'), // same names, other position
  mk('Boundary', 'cliff|RB|E Five'),
  mk('Hook recall', 'hook|A One|pass-catcher'),
  mk('Who goes earlier?', 'pair|E Five|F Six'),
  mk('Plan recall', 'plan|3|Best available: RB t2'),
];
const state = { session: 9, boxes: Object.fromEntries(oldDeck.map(c => [c.id, 3])) };
const meta = Object.fromEntries(oldDeck.map(c => [c.id, { type: c.type, key: c.key }]));
const newDeck = [
  mk('Tier recall', 'recall|RB|A One, B Two, C Three, D Four, F Six'), // one name swapped: 4/6 overlap
  mk('Boundary', 'cliff|RB|E Five'),                                   // unchanged id
  mk('Tier recall', 'recall|TE|X Ten, Y Eleven'),                      // genuinely new fact
  mk('Hook recall', 'hook|A One|rushing floor'),                       // same player, new hook text
  mk('Who goes earlier?', 'pair|F Six|E Five'),                        // reordered pair
  mk('Plan recall', 'plan|3|Best available: WR t1'),                   // plans never migrate
];
S.migrate(newDeck, state, meta);
const box = c => state.boxes[c.id];
const checks = [
  ['overlapping tier inherits box', box(newDeck[0]) === 3],
  ['stable id keeps box', box(newDeck[1]) === 3],
  ['new fact starts fresh', box(newDeck[2]) === undefined],
  ['hook follows the player', box(newDeck[3]) === 3],
  ['pair is order-insensitive', box(newDeck[4]) === 3],
  ['plan card resets', box(newDeck[5]) === undefined],
  ['same names, other position, not consumed', state.boxes[oldDeck[1].id] === 3],
];
// idempotence on the live deck: migrating an already-known deck moves nothing
const liveState = { session: 0, boxes: Object.fromEntries(deck.map(c => [c.id, 2])) };
const liveMeta = S.migrate(deck, liveState, {});
checks.push(['live deck is a no-op', deck.every(c => liveState.boxes[c.id] === 2) && Object.keys(liveMeta).length >= deck.length]);
let migrateFail = 0;
for (const [name, ok] of checks) { if (!ok) migrateFail++; console.log(`migration: ${name}: ${ok ? 'ok' : 'FAIL'}`); }

process.exit(dupes || unknown.length || !noTierNum || migrateFail || rowFail ? 1 : 0);
