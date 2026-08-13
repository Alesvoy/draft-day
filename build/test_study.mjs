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

const store = new Map();
const localStorage = {
  getItem: k => store.has(k) ? store.get(k) : null,
  setItem: (k, v) => store.set(k, String(v)),
};
const make = new Function('BOARD', 'localStorage', 'location', 'document', 'LEGACY',
  logic.replace('const BOARD=__BOARD_JSON__;', '').replace('const LEGACY_META=__LEGACY_META__;', 'const LEGACY_META=LEGACY;') +
  '\nreturn {cards,card,migrate,TIERS,POSITIONS,bandOf,isCliff,BAND_A_END,BAND_B_END,CLIFF,draftable};');
const S = make(BOARD, localStorage, { hash: '' }, { querySelector: () => null }, {});

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

process.exit(dupes || unknown.length || !noTierNum || migrateFail ? 1 : 0);
