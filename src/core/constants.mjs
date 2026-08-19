export const APP_VERSION = '3.0.0-pre.2';
export const XRAY_VERSION = 'v26.7.28';
export const PRIMARY_SUBSCRIPTION = 'https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt';
export const SUPPORTED_SCHEMES = new Set(['vmess:', 'vless:', 'trojan:', 'ss:', 'socks:', 'http:', 'https:', 'hysteria2:', 'hy2:']);
export const DEFAULT_PROBE_TARGETS = Object.freeze([
  { host: 'www.gstatic.com', port: 443, path: '/generate_204', tls: true },
  { host: 'www.apple.com', port: 443, path: '/library/test/success.html', tls: true },
  { host: 'cp.cloudflare.com', port: 443, path: '/generate_204', tls: true }
]);
export const IRAN_TUNING = Object.freeze({
  concurrency: 12,
  attempts: 3,
  connectTimeoutMs: 6500,
  requestTimeoutMs: 10000,
  staggerMs: 35,
  preferIpv4: true,
  successThreshold: 2,
  dns: ['https://1.1.1.1/dns-query', 'https://8.8.8.8/dns-query'],
  fallbackDns: ['1.1.1.1', '8.8.8.8']
});
