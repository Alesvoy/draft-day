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
const make = new Function('BOARD', 'localStorage', 'location', 'document',
  logic.replace('const BOARD=__BOARD_JSON__;', '') +
  '\nreturn {cards,TIERS,POSITIONS,bandOf,isCliff,BAND_A_END,BAND_B_END,CLIFF,draftable};');
const S = make(BOARD, localStorage, { hash: '' }, { querySelector: () => null });

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
process.exit(dupes || unknown.length || !noTierNum ? 1 : 0);
