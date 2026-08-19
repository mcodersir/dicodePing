function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : Math.round((sorted[middle - 1] + sorted[middle]) / 2);
}

export function summarizeAttempts(attempts) {
  const passed = attempts.filter(x => x.ok);
  const totals = passed.map(x => x.totalMs);
  const med = median(totals);
  const jitter = totals.length > 1 ? median(totals.slice(1).map((x, i) => Math.abs(x - totals[i]))) : 0;
  const loss = attempts.length ? Math.round((1 - passed.length / attempts.length) * 100) : 100;
  const score = med == null ? 0 : Math.max(0, Math.round(100 - med / 12 - jitter / 8 - loss * 0.7));
  return { ok: passed.length >= Math.ceil(attempts.length / 2), medianMs: med, jitterMs: jitter, lossPercent: loss, score, attempts };
}
