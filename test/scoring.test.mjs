import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeAttempts } from '../src/core/scoring.mjs';
import { mapConcurrent } from '../src/core/scanner.mjs';

test('quality uses median, jitter and loss instead of a fake single ping', () => {
  const value = summarizeAttempts([{ ok: true, totalMs: 100 }, { ok: false, totalMs: 5000 }, { ok: true, totalMs: 140 }]);
  assert.equal(value.ok, true); assert.equal(value.medianMs, 120); assert.equal(value.jitterMs, 40); assert.equal(value.lossPercent, 33); assert.ok(value.score > 0 && value.score < 100);
});

test('bounded scheduler never exceeds requested concurrency', async () => {
  let active = 0, peak = 0;
  const rows = await mapConcurrent([1,2,3,4,5,6], async value => { active++; peak = Math.max(peak, active); await new Promise(r => setTimeout(r, 5)); active--; return value * 2; }, { concurrency: 2 });
  assert.deepEqual(rows, [2,4,6,8,10,12]); assert.equal(peak, 2);
});
