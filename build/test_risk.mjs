#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const HERE = path.dirname(url.fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const BOARD = JSON.parse(fs.readFileSync(path.join(ROOT, 'board.json'), 'utf8'));
const tpl = fs.readFileSync(path.join(HERE, 'app_template.html'), 'utf8');
const source = tpl.match(/\/\*ENGINE-START\*\/([\s\S]*?)\/\*ENGINE-END\*\//)?.[1];
if (!source) throw new Error('engine markers not found');
const makeEngine = new Function('BOARD', 'localStorage', source + `
  return {state, applyCfg, planContext, scoreOf};`);
const engine = makeEngine(BOARD, {getItem:()=>null,setItem:()=>{}});
engine.state.slot = 1; engine.state.picks = []; engine.state.cfg = {teams:14,scoring:'std',rounds:18}; engine.applyCfg();
const player = BOARD.players.find(p => p.proj_pts != null && p.vor > 0);
if (!player) throw new Error('no projected player found');
const ctx = engine.planContext();
const original = structuredClone(player.forecast);
const stats = player.forecast.by_scoring.std;
player.forecast.by_scoring.std = {market:stats.market,expected:stats.market,floor:stats.market,ceiling:stats.market};
player.forecast.availability_risk = 'low'; player.forecast.reasons = [];
const neutral = engine.scoreOf(player, ctx);
player.forecast.by_scoring.std = {market:stats.market,expected:stats.market*.55,floor:stats.market*.2,ceiling:stats.market};
player.forecast.availability_risk = 'high'; player.forecast.reasons = ['confirmed missed time'];
const risky = engine.scoreOf(player, ctx);
player.forecast = original;
if (!(risky.s < neutral.s)) throw new Error(`risk did not lower score: ${risky.s} >= ${neutral.s}`);
if (!('draftAvailabilityRisk' in risky) || 'riskLoss' in risky) throw new Error('draft availability field was not renamed');
if (!risky.reasons.some(reason => reason.includes('availability risk'))) throw new Error('risk reason not surfaced');
if (/FANTASYPROS_API_KEY|x-api-key/i.test(tpl)) throw new Error('credential reference leaked into app template');
console.log(`RISK CHECK OK — ${player.name} score ${neutral.s.toFixed(1)} -> ${risky.s.toFixed(1)}`);
