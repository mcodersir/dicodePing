import net from 'node:net';
import tls from 'node:tls';
import { performance } from 'node:perf_hooks';

const socketRemainders = new WeakMap();

export function readExactly(socket, length, timeoutMs) {
  return new Promise((resolve, reject) => {
    let buffer = socketRemainders.get(socket) || Buffer.alloc(0);
    socketRemainders.delete(socket);
    const timer = setTimeout(() => finish(new Error('SOCKS read timeout')), timeoutMs);
    function finish(error, value) {
      clearTimeout(timer); socket.off('data', onData); socket.off('error', onError);
      error ? reject(error) : resolve(value);
    }
    function onError(error) { finish(error); }
    function onData(chunk) {
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length >= length) {
        const value = buffer.subarray(0, length);
        const rest = buffer.subarray(length);
        if (rest.length) socketRemainders.set(socket, Buffer.from(rest));
        finish(null, value);
      }
    }
    socket.on('data', onData); socket.once('error', onError);
    if (buffer.length >= length) {
      const value = buffer.subarray(0, length);
      const rest = buffer.subarray(length);
      if (rest.length) socketRemainders.set(socket, Buffer.from(rest));
      finish(null, value);
    }
  });
}

async function socksConnect({ socksPort, host, port, timeoutMs }) {
  const socket = net.connect({ host: '127.0.0.1', port: socksPort });
  socket.setNoDelay(true);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { socket.destroy(); reject(new Error('SOCKS connect timeout')); }, timeoutMs);
    socket.once('connect', () => { clearTimeout(timer); resolve(); });
    socket.once('error', error => { clearTimeout(timer); reject(error); });
  });
  socket.write(Buffer.from([5, 1, 0]));
  const auth = await readExactly(socket, 2, timeoutMs);
  if (auth[0] !== 5 || auth[1] !== 0) throw new Error('SOCKS proxy rejected no-auth negotiation');
  const domain = Buffer.from(host, 'utf8');
  if (domain.length > 255) throw new Error('probe hostname too long');
  socket.write(Buffer.concat([Buffer.from([5, 1, 0, 3, domain.length]), domain, Buffer.from([port >> 8, port & 255])]));
  const head = await readExactly(socket, 4, timeoutMs);
  if (head[1] !== 0) throw new Error(`SOCKS connect failed (${head[1]})`);
  const addressLength = head[3] === 1 ? 4 : head[3] === 4 ? 16 : (await readExactly(socket, 1, timeoutMs))[0];
  await readExactly(socket, addressLength + 2, timeoutMs);
  return socket;
}

export async function realPathProbe(socksPort, target, { timeoutMs = 10_000, maxBytes = 64 * 1024 } = {}) {
  const started = performance.now();
  let socket;
  try {
    socket = await socksConnect({ socksPort, host: target.host, port: target.port, timeoutMs });
    const tunnelMs = performance.now() - started;
    const secure = target.tls ? tls.connect({ socket, servername: target.host, ALPNProtocols: ['http/1.1'], rejectUnauthorized: true }) : socket;
    if (target.tls) await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('TLS handshake timeout')), timeoutMs);
      secure.once('secureConnect', () => { clearTimeout(timer); resolve(); });
      secure.once('error', error => { clearTimeout(timer); reject(error); });
    });
    const tlsMs = performance.now() - started;
    const request = `GET ${target.path} HTTP/1.1\r\nHost: ${target.host}\r\nUser-Agent: DicodePing/3\r\nAccept: */*\r\nConnection: close\r\n\r\n`;
    secure.write(request);
    const response = await new Promise((resolve, reject) => {
      let bytes = 0, firstByteMs = null, header = '';
      const timer = setTimeout(() => reject(new Error('HTTP probe timeout')), timeoutMs);
      secure.on('data', chunk => {
        if (firstByteMs == null) firstByteMs = performance.now() - started;
        bytes += chunk.length;
        if (header.length < 4096) header += chunk.toString('latin1');
        if (bytes >= maxBytes || header.includes('\r\n\r\n')) {
          clearTimeout(timer); resolve({ bytes, firstByteMs, header }); secure.destroy();
        }
      });
      secure.once('end', () => { clearTimeout(timer); resolve({ bytes, firstByteMs, header }); });
      secure.once('error', error => { clearTimeout(timer); reject(error); });
    });
    const status = Number(response.header.match(/^HTTP\/\d(?:\.\d)?\s+(\d{3})/i)?.[1] || 0);
    if (status < 200 || status >= 500) throw new Error(`probe HTTP status ${status || 'invalid'}`);
    return { ok: true, tunnelMs: Math.round(tunnelMs), tlsMs: Math.round(tlsMs), firstByteMs: Math.round(response.firstByteMs), totalMs: Math.round(performance.now() - started), status, bytes: response.bytes };
  } catch (error) {
    socket?.destroy();
    return { ok: false, totalMs: Math.round(performance.now() - started), error: error.message };
  }
}
