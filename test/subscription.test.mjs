import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchSubscription, validateSubscriptionUrl } from '../src/core/subscription.mjs';

test('subscription validator rejects local and credential URLs', () => {
  assert.throws(() => validateSubscriptionUrl('file:///tmp/a'));
  assert.throws(() => validateSubscriptionUrl('https://localhost/sub'));
  assert.throws(() => validateSubscriptionUrl('https://user:pass@example.com/sub'));
});

test('subscription enforces declared and actual byte limits', async () => {
  const fetchImpl = async () => new Response('trojan://a@example.com:443#x', { status: 200, headers: { 'content-length': '999' } });
  await assert.rejects(fetchSubscription('https://example.com/sub', { maxBytes: 50, fetchImpl }), /size limit/);
});
