#!/usr/bin/env node
// Parity harness: runs the pure-logic engine slice of app_template.html through
// deterministic scripted drafts and dumps every recommendation with full precision.
//
//   node build/test_parity.mjs --board build/golden/board.baseline.json \
//       --out build/golden/engine.baseline.json
//   node build/test_parity.mjs --board board.json --compare build/golden/engine.baseline.json
//
// With --compare, exits 1 on any drift from the golden file (used to prove the
// 14-team / standard / 18-round default is untouched by the config work).
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 ? process.argv[i + 1] : dflt;
}
const boardPath = path.resolve(ROOT, arg('board', 'board.json'));
const outPath = arg('out') ? path.resolve(ROOT, arg('out')) : null;
const comparePath = arg('compare') ? path.resolve(ROOT, arg('compare')) : null;

const BOARD = JSON.parse(fs.readFileSync(boardPath, 'utf8'));
const tpl = fs.readFileSync(path.join(HERE, 'app_template.html'), 'utf8');
const m = tpl.match(/\/\*ENGINE-START\*\/([\s\S]*?)\/\*ENGINE-END\*\//);
if (!m) { console.error('ENGINE markers not found in app_template.html'); process.exit(2); }

// The engine references localStorage (load/save) and nothing else outside the slice.
const makeEngine = new Function('BOARD', 'localStorage', m[1] + `
  return {
    state,
    hooks: {
      applyCfg: (typeof applyCfg === 'function') ? applyCfg : null,
      scoreOf, planContext, pVor,
    },
    recommendations, positionalLean, teamOnClock, roundPick,
    get TEAMS(){ return TEAMS; }, get ROSTER_SLOTS(){ return ROSTER_SLOTS; },
  };`);
const fakeLS = { getItem: () => null, setItem: () => {} };

// Deterministic opponent policies.
const POLICIES = {
  adp: (pool) => pool.slice().sort((a, b) =>
    (a.adp ?? 1e9) - (b.adp ?? 1e9) || a.ecr - b.ecr)[0],
  ecr: (pool) => pool.slice().sort((a, b) => a.ecr - b.ecr)[0],
};

const CFG = process.argv.includes('--cfg')
  ? JSON.parse(arg('cfg')) : null; // e.g. '{"teams":10,"scoring":"full","rounds":15}'

if (process.argv.includes('--check-scoring')) {
  const errors = [];
  const ti = BOARD.meta.team_options.indexOf(14);

  for (const p of BOARD.players) {
    if (p.proj_pts == null) continue;
    const rec = p.rec || 0;
    if (Math.abs(p.proj_m?.half - (p.proj_pts + 0.5 * rec)) > 0.11) errors.push(`${p.name}: bad half-PPR projection`);
    if (Math.abs(p.proj_m?.full - (p.proj_pts + rec)) > 0.11) errors.push(`${p.name}: bad full-PPR projection`);
  }

  for (const scoring of ['std', 'half', 'full']) {
    const ranks = BOARD.meta.replacement_rank_m[scoring];
    BOARD.meta.team_options.forEach((teams, i) => {
      const base = teams * 2;
      const flex = (ranks.RB[i] - base) + (ranks.WR[i] - base);
      if (flex !== teams) errors.push(`${teams}-team ${scoring}: ${flex} flex replacements allocated`);
    });
  }

  function configured(scoring) {
    const eng = makeEngine(BOARD, fakeLS);
    eng.state.slot = 7;
    eng.state.picks = [];
    eng.state.cfg = { teams: 14, scoring, rounds: 18 };
    eng.hooks.applyCfg();
    return eng;
  }
  const std = configured('std'), full = configured('full');
  const stdNames = std.recommendations().list.map(r => r.p.name);
  const fullNames = full.recommendations().list.map(r => r.p.name);
  if (JSON.stringify(stdNames) === JSON.stringify(fullNames)) errors.push('standard and full-PPR recommendations are identical');

  const top100 = BOARD.players.filter(p => p.ecr <= 100 && p.rec != null);
  const highRecWR = top100.filter(p => p.pos === 'WR').sort((a, b) => b.rec - a.rec)[0];
  const lowRecRB = top100.filter(p => p.pos === 'RB').sort((a, b) => a.rec - b.rec)[0];
  const wrLift = highRecWR.vor_m.full[ti] - highRecWR.vor_m.std[ti];
  const rbLift = lowRecRB.vor_m.full[ti] - lowRecRB.vor_m.std[ti];
  if (!(wrLift > rbLift)) errors.push('full PPR does not favor a high-reception WR over a low-reception RB');

  if (errors.length) {
    errors.forEach(e => console.error(`SCORING CHECK FAILED: ${e}`));
    process.exit(1);
  }
  console.log(`SCORING CHECK OK — recommendations change; ${highRecWR.name} gains relative to ${lowRecRB.name}`);
  process.exit(0);
}

function runScenario(seat, policyName) {
  const eng = makeEngine(BOARD, fakeLS);
  eng.state.slot = seat;
  eng.state.picks = [];
  if (CFG && eng.hooks.applyCfg) { eng.state.cfg = CFG; eng.hooks.applyCfg(); }
  const pick = POLICIES[policyName];
  const byName = {}; BOARD.players.forEach(p => { byName[p.name] = p; });
  const total = eng.TEAMS * eng.ROSTER_SLOTS;
  const turns = [];
  for (let i = 0; i < total; i++) {
    const drafted = new Set(eng.state.picks);
    const pool = BOARD.players.filter(p => !drafted.has(p.name));
    if (!pool.length) break;
    if (eng.teamOnClock(i) === seat) {
      const { ctx, list } = eng.recommendations();
      const lean = eng.positionalLean().best;
      turns.push({
        overall: i + 1,
        round: eng.roundPick(i).round,
        lean: lean ? lean.pos : null,
        recs: list.map(r => ({ name: r.p.name, s: r.s, reasons: r.reasons, draftAvailabilityRisk: r.draftAvailabilityRisk })),
      });
      eng.state.picks.push(list.length ? list[0].p.name : pool[0].name);
    } else {
      eng.state.picks.push(pick(pool).name);
    }
  }
  return turns;
}

// Seats: first, middle, last — [1,7,14] at the 14-team default.
const probe = makeEngine(BOARD, fakeLS);
if (CFG && probe.hooks.applyCfg) { probe.state.cfg = CFG; probe.hooks.applyCfg(); }
const T = probe.TEAMS;
const result = {};
for (const seat of [1, Math.ceil(T / 2), T]) {
  for (const policyName of Object.keys(POLICIES)) {
    result[`seat${seat}_${policyName}`] = runScenario(seat, policyName);
  }
}
const json = JSON.stringify(result, null, 1);

if (outPath) {
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, json);
  console.log(`Wrote ${outPath} (${Object.keys(result).length} scenarios)`);
}
if (comparePath) {
  const golden = fs.readFileSync(comparePath, 'utf8');
  if (golden === json) {
    console.log('PARITY OK — engine output byte-identical to golden');
  } else {
    const g = JSON.parse(golden);
    for (const k of Object.keys(g)) {
      const a = JSON.stringify(g[k]), b = JSON.stringify(result[k]);
      if (a !== b) {
        let at = 0; while (a[at] === b[at]) at++;
        console.error(`DRIFT in ${k} @char ${at}:\n  golden: …${a.slice(Math.max(0, at - 60), at + 80)}…\n  new:    …${b.slice(Math.max(0, at - 60), at + 80)}…`);
        break;
      }
    }
    console.error('PARITY FAILED');
    process.exit(1);
  }
}
if (!outPath && !comparePath) console.log(json.slice(0, 2000));
