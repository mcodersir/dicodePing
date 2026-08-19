import test from 'node:test';
import assert from 'node:assert/strict';
import { Buffer } from 'node:buffer';
import { parseProfile, parseProfileList } from '../src/core/profiles.mjs';

test('parses modern VLESS Reality options', () => {
  const p = parseProfile('vless://11111111-1111-1111-1111-111111111111@example.com:443?security=reality&type=xhttp&sni=cdn.example.com&fp=chrome&pbk=abc&sid=12#fast');
  assert.equal(p.protocol, 'vless'); assert.equal(p.options.security, 'reality'); assert.equal(p.options.network, 'xhttp'); assert.equal(p.name, 'fast');
});

test('parses legacy vmess and URL-safe base64 subscriptions', () => {
  const vmess = `vmess://${Buffer.from(JSON.stringify({ v: '2', ps: 'node', add: '1.2.3.4', port: '443', id: 'u', net: 'ws', tls: 'tls' })).toString('base64')}`;
  const subscription = Buffer.from(`${vmess}\n${vmess}`).toString('base64url');
  const result = parseProfileList(subscription);
  assert.equal(result.profiles.length, 1); assert.equal(result.profiles[0].options.network, 'ws');
});

test('parses both SIP002 shadowsocks encodings', () => {
  const credentials = Buffer.from('aes-128-gcm:secret').toString('base64url');
  assert.equal(parseProfile(`ss://${credentials}@example.com:8388#node`).options.method, 'aes-128-gcm');
  assert.equal(parseProfile(`ss://${Buffer.from('aes-128-gcm:secret@example.com:8388').toString('base64')}#node`).port, 8388);
});

test('deduplicates profiles and reports malformed input', () => {
  const raw = 'trojan://secret@example.com:443#one';
  const result = parseProfileList(`${raw}\n${raw}\nvless://bad`);
  assert.equal(result.profiles.length, 1); assert.equal(result.errors.length, 1);
});
