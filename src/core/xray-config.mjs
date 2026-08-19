import { IRAN_TUNING } from './constants.mjs';

function streamSettings(o) {
  const settings = { network: o.network || 'tcp', security: o.security || 'none' };
  if (o.security === 'tls') settings.tlsSettings = { serverName: o.sni || o.host || '', fingerprint: o.fingerprint || 'chrome', alpn: o.alpn ? o.alpn.split(',') : undefined };
  if (o.security === 'reality') settings.realitySettings = { serverName: o.sni, fingerprint: o.fingerprint || 'chrome', publicKey: o.publicKey, shortId: o.shortId, spiderX: o.spiderX || '/' };
  if (o.network === 'ws') settings.wsSettings = { path: o.path || '/', headers: o.host ? { Host: o.host } : {} };
  if (o.network === 'grpc') settings.grpcSettings = { serviceName: o.serviceName || '', multiMode: false };
  if (o.network === 'httpupgrade') settings.httpupgradeSettings = { path: o.path || '/', host: o.host || '' };
  if (o.network === 'xhttp') settings.xhttpSettings = { path: o.path || '/', host: o.host || '', mode: 'auto' };
  return settings;
}

export function profileToOutbound(profile, tag = `proxy-${profile.id}`) {
  const p = profile, o = p.options;
  if (p.protocol === 'vmess') return { tag, protocol: 'vmess', settings: { vnext: [{ address: p.host, port: p.port, users: [{ id: o.uuid, alterId: o.alterId || 0, security: o.security || 'auto' }] }] }, streamSettings: streamSettings(o) };
  if (p.protocol === 'vless') return { tag, protocol: 'vless', settings: { vnext: [{ address: p.host, port: p.port, users: [{ id: o.uuid, encryption: o.encryption || 'none', flow: o.flow || undefined }] }] }, streamSettings: streamSettings(o) };
  if (p.protocol === 'trojan') return { tag, protocol: 'trojan', settings: { servers: [{ address: p.host, port: p.port, password: o.uuid || o.username }] }, streamSettings: streamSettings(o) };
  if (p.protocol === 'shadowsocks') return { tag, protocol: 'shadowsocks', settings: { servers: [{ address: p.host, port: p.port, method: o.method, password: o.password }] } };
  if (p.protocol === 'socks') return { tag, protocol: 'socks', settings: { servers: [{ address: p.host, port: p.port, users: o.username ? [{ user: o.username, pass: o.password }] : undefined }] } };
  if (p.protocol === 'http' || p.protocol === 'https') return { tag, protocol: 'http', settings: { servers: [{ address: p.host, port: p.port, users: o.username ? [{ user: o.username, pass: o.password }] : undefined }] } };
  if (p.protocol === 'hysteria2') return { tag, protocol: 'hysteria2', settings: { servers: [{ address: p.host, port: p.port, password: o.uuid || o.username }] }, streamSettings: streamSettings({ ...o, network: 'hysteria2' }) };
  throw new Error(`Xray does not support ${p.protocol}`);
}

export function createClientConfig(profile, { socksPort = 2080, httpPort = 2081 } = {}) {
  return {
    log: { loglevel: 'warning' },
    dns: { servers: [...IRAN_TUNING.dns, ...IRAN_TUNING.fallbackDns], queryStrategy: IRAN_TUNING.preferIpv4 ? 'UseIPv4' : 'UseIP' },
    inbounds: [
      { tag: 'socks-in', listen: '127.0.0.1', port: socksPort, protocol: 'socks', settings: { udp: true } },
      { tag: 'http-in', listen: '127.0.0.1', port: httpPort, protocol: 'http', settings: {} }
    ],
    outbounds: [profileToOutbound(profile, 'proxy'), { tag: 'direct', protocol: 'freedom' }, { tag: 'block', protocol: 'blackhole' }],
    routing: { domainStrategy: 'IPIfNonMatch', rules: [{ type: 'field', ip: ['geoip:private'], outboundTag: 'direct' }] },
    policy: { system: { statsOutboundUplink: true, statsOutboundDownlink: true } },
    stats: {}
  };
}

export function createBatchProbeConfig(profiles, portInput = 24000) {
  const ports = Array.isArray(portInput) ? portInput : profiles.map((_, index) => portInput + index);
  const inbounds = [], outbounds = [], rules = [];
  profiles.forEach((profile, index) => {
    const inboundTag = `probe-in-${index}`, outboundTag = `probe-out-${index}`;
    inbounds.push({ tag: inboundTag, listen: '127.0.0.1', port: ports[index], protocol: 'socks', settings: { udp: false } });
    outbounds.push(profileToOutbound(profile, outboundTag));
    rules.push({ type: 'field', inboundTag: [inboundTag], outboundTag });
  });
  return { config: { log: { loglevel: 'warning' }, inbounds, outbounds, routing: { domainStrategy: 'IPIfNonMatch', rules } }, ports };
}
