export function decodeBase64Flexible(value) {
  const compact = String(value ?? '').trim().replace(/\s+/g, '').replace(/-/g, '+').replace(/_/g, '/');
  if (!compact || !/^[A-Za-z0-9+/]*={0,2}$/.test(compact)) throw new Error('invalid base64');
  const padded = compact + '='.repeat((4 - compact.length % 4) % 4);
  return Buffer.from(padded, 'base64').toString('utf8');
}

export function maybeDecodeSubscription(value) {
  const text = String(value ?? '').replace(/^\uFEFF/, '').trim();
  if (/\b(?:vmess|vless|trojan|ss|socks|hy2|hysteria2):\/\//i.test(text)) return text;
  try {
    const decoded = decodeBase64Flexible(text);
    return /:\/\//.test(decoded) ? decoded : text;
  } catch {
    return text;
  }
}
