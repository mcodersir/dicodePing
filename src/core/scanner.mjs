import { IRAN_TUNING } from './constants.mjs';
import { summarizeAttempts } from './scoring.mjs';

export async function mapConcurrent(items, worker, { concurrency = IRAN_TUNING.concurrency, signal, onProgress } = {}) {
  const results = new Array(items.length);
  let cursor = 0, done = 0;
  async function lane() {
    while (true) {
      if (signal?.aborted) throw signal.reason ?? new Error('scan cancelled');
      const index = cursor++;
      if (index >= items.length) return;
      try { results[index] = await worker(items[index], index); }
      catch (error) { results[index] = { ok: false, error: error.message }; }
      done += 1;
      onProgress?.({ done, total: items.length, index, result: results[index] });
    }
  }
  await Promise.all(Array.from({ length: Math.min(Math.max(1, concurrency), items.length) }, lane));
  return results;
}

export async function scanProfiles(profiles, probe, options = {}) {
  const attempts = options.attempts ?? IRAN_TUNING.attempts;
  const rows = await mapConcurrent(profiles, async profile => {
    const samples = [];
    for (let i = 0; i < attempts; i += 1) samples.push(await probe(profile, i));
    return { profile, ...summarizeAttempts(samples) };
  }, options);
  return rows.sort((a, b) => Number(b.ok) - Number(a.ok) || (b.score ?? 0) - (a.score ?? 0));
}
