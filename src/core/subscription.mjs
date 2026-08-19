import { parseProfileList } from './profiles.mjs';
import { PRIMARY_SUBSCRIPTION } from './constants.mjs';

export function validateSubscriptionUrl(value) {
  const url = new URL(String(value));
  if (!['https:', 'http:'].includes(url.protocol)) throw new Error('subscription must use HTTP(S)');
  if (url.username || url.password) throw new Error('credentials in subscription URL are not allowed');
  if (['localhost', '0.0.0.0', '::1'].includes(url.hostname)) throw new Error('local subscription URL is not allowed');
  return url;
}

export async function fetchSubscription(value = PRIMARY_SUBSCRIPTION, { signal, maxBytes = 4_000_000, fetchImpl = fetch } = {}) {
  const url = validateSubscriptionUrl(value);
  const response = await fetchImpl(url, { signal, redirect: 'follow', headers: { 'user-agent': 'DicodePing/3', accept: 'text/plain,*/*;q=0.2' } });
  if (!response.ok) throw new Error(`subscription HTTP ${response.status}`);
  const announced = Number(response.headers.get('content-length') || 0);
  if (announced > maxBytes) throw new Error('subscription exceeds size limit');
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > maxBytes) throw new Error('subscription exceeds size limit');
  const parsed = parseProfileList(new TextDecoder().decode(bytes));
  return { ...parsed, source: url.href, fetchedAt: new Date().toISOString() };
}
