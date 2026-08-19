import net from 'node:net';
import { DEFAULT_PROBE_TARGETS, IRAN_TUNING } from '../core/constants.mjs';
import { createBatchProbeConfig } from '../core/xray-config.mjs';
import { summarizeAttempts } from '../core/scoring.mjs';
import { realPathProbe } from './socks-probe.mjs';
import { startXray } from './xray-supervisor.mjs';

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref(); server.once('error', reject);
    server.listen(0, '127.0.0.1', () => { const port = server.address().port; server.close(() => resolve(port)); });
  });
}

export async function scanWithXray(profiles, { onProgress, signal, batchSize = 10, attempts = IRAN_TUNING.attempts } = {}) {
  const all = [];
  for (let offset = 0; offset < profiles.length; offset += batchSize) {
    if (signal?.aborted) throw new Error('scan cancelled');
    const batch = profiles.slice(offset, offset + batchSize);
    const ports = await Promise.all(batch.map(() => freePort()));
    const { config } = createBatchProbeConfig(batch, ports);
    const runtime = await startXray(config, ports[0]);
    try {
      const rows = await Promise.all(batch.map(async (profile, index) => {
        const samples = [];
        for (let attempt = 0; attempt < attempts; attempt += 1) {
          const target = DEFAULT_PROBE_TARGETS[attempt % DEFAULT_PROBE_TARGETS.length];
          samples.push(await realPathProbe(ports[index], target, { timeoutMs: IRAN_TUNING.requestTimeoutMs }));
        }
        const row = { profile, ...summarizeAttempts(samples) };
        onProgress?.({ done: offset + index + 1, total: profiles.length, row });
        return row;
      }));
      all.push(...rows);
    } finally { await runtime.stop(); }
  }
  return all.sort((a, b) => Number(b.ok) - Number(a.ok) || b.score - a.score);
}
