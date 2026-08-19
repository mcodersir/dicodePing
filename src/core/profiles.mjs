import { createHash } from 'node:crypto';
import { decodeBase64Flexible, maybeDecodeSubscription } from './base64.mjs';
import { SUPPORTED_SCHEMES } from './constants.mjs';

function asPort(value) {
  const port = Number(value);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('invalid port');
  return port;
}

function idFor(raw) {
  return createHash('sha256').update(raw).digest('hex').slice(0, 20);
}

function common(raw, protocol, host, port, name, options = {}) {
  if (!host || /\s/.test(host)) throw new Error('invalid host');
  return { id: idFor(raw), raw, protocol, host, port: asPort(port), name: name || `${protocol} ${host}`, options };
}

function parseVmess(raw) {
  const data = JSON.parse(decodeBase64Flexible(raw.slice('vmess://'.length)));
  return common(raw, 'vmess', data.add, data.port, data.ps, {
    uuid: data.id, alterId: Number(data.aid || 0), security: data.scy || 'auto',
    network: data.net || 'tcp', tls: data.tls || '', sni: data.sni || data.host || '',
    host: data.host || '', path: data.path || '', fingerprint: data.fp || 'chrome', alpn: data.alpn || ''
  });
}

function parseStandard(raw) {
  const url = new URL(raw);
  if (!SUPPORTED_SCHEMES.has(url.protocol)) throw new Error(`unsupported scheme ${url.protocol}`);
  const p = Object.fromEntries(url.searchParams);
  const protocol = url.protocol.replace(':', '') === 'hy2' ? 'hysteria2' : url.protocol.replace(':', '');
  if (['vless', 'trojan', 'hysteria2'].includes(protocol) && !url.username) throw new Error(`${protocol} credential is required`);
  return common(raw, protocol, url.hostname, url.port || (url.protocol === 'https:' ? 443 : 1080), decodeURIComponent(url.hash.slice(1)), {
    username: decodeURIComponent(url.username), password: decodeURIComponent(url.password),
    uuid: decodeURIComponent(url.username), security: p.security || (protocol === 'trojan' ? 'tls' : ''),
    encryption: p.encryption || 'none', flow: p.flow || '', network: p.type || 'tcp',
    headerType: p.headerType || '', host: p.host || '', path: p.path || '', serviceName: p.serviceName || '',
    sni: p.sni || p.peer || '', fingerprint: p.fp || 'chrome', publicKey: p.pbk || '', shortId: p.sid || '',
    spiderX: p.spx || '', alpn: p.alpn || '', insecure: p.allowInsecure === '1'
  });
}

function parseShadowsocks(raw) {
  let body = raw.slice(5);
  let name = '';
  const hash = body.indexOf('#');
  if (hash >= 0) { name = decodeURIComponent(body.slice(hash + 1)); body = body.slice(0, hash); }
  const queryAt = body.indexOf('?');
  if (queryAt >= 0) body = body.slice(0, queryAt);
  if (!body.includes('@')) body = decodeBase64Flexible(body);
  else {
    const at = body.lastIndexOf('@');
    const userInfo = body.slice(0, at);
    if (!userInfo.includes(':')) body = `${decodeBase64Flexible(userInfo)}${body.slice(at)}`;
  }
  const match = body.match(/^(.+?):(.+)@\[?([^\]]+)\]?:([0-9]+)$/);
  if (!match) throw new Error('invalid shadowsocks URI');
  return common(raw, 'shadowsocks', match[3], match[4], name, { method: match[1], password: match[2] });
}

export function parseProfile(rawValue) {
  const raw = String(rawValue ?? '').trim();
  if (raw.startsWith('vmess://')) return parseVmess(raw);
  if (raw.startsWith('ss://')) return parseShadowsocks(raw);
  return parseStandard(raw);
}

export function parseProfileList(input) {
  const text = maybeDecodeSubscription(input);
  const candidates = text.split(/[\r\n\t ]+/).map(x => x.trim()).filter(x => /^(?:vmess|vless|trojan|ss|socks|http|https|hy2|hysteria2):\/\//i.test(x));
  const profiles = [], errors = [], seen = new Set();
  for (const raw of candidates) {
    try {
      const profile = parseProfile(raw);
      if (!seen.has(profile.id)) { seen.add(profile.id); profiles.push(profile); }
    } catch (error) {
      errors.push({ raw: raw.slice(0, 160), error: error.message });
    }
  }
  return { profiles, errors };
}
