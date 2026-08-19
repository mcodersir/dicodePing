import test from 'node:test';
import assert from 'node:assert/strict';
import { parseProfile } from '../src/core/profiles.mjs';
import { createBatchProbeConfig, createClientConfig, profileToOutbound } from '../src/core/xray-config.mjs';

test('builds isolated outbound for Reality', () => {
  const p = parseProfile('vless://id@host.example:443?security=reality&sni=front.example&pbk=key&sid=aa&type=tcp#r');
  const outbound = profileToOutbound(p);
  assert.equal(outbound.protocol, 'vless'); assert.equal(outbound.streamSettings.realitySettings.serverName, 'front.example');
});

test('batch scanner routes every inbound to only its candidate', () => {
  const profiles = [parseProfile('trojan://a@one.example:443#a'), parseProfile('socks://two.example:1080#b')];
  const { config, ports } = createBatchProbeConfig(profiles, [30100, 30104]);
  assert.deepEqual(ports, [30100, 30104]); assert.equal(config.routing.rules.length, 2); assert.equal(config.outbounds.length, 2);
});

test('client exposes loopback only', () => {
  const config = createClientConfig(parseProfile('trojan://a@one.example:443#a'));
  assert.ok(config.inbounds.every(x => x.listen === '127.0.0.1'));
});
