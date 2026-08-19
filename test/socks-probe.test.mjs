import test from 'node:test';
import assert from 'node:assert/strict';
import { PassThrough } from 'node:stream';
import net from 'node:net';
import http from 'node:http';
import { readExactly, realPathProbe } from '../src/desktop/socks-probe.mjs';

test('SOCKS reader buffers surplus bytes without recursive consumption', async () => {
  const socket = new PassThrough();
  const first = readExactly(socket, 2, 1000);
  socket.write(Buffer.from([1, 2, 3, 4]));
  assert.deepEqual([...await first], [1, 2]);
  assert.deepEqual([...await readExactly(socket, 2, 1000)], [3, 4]);
  socket.destroy();
});

test('real-path probe completes an HTTP request through SOCKS5', async t => {
  const target = http.createServer((_, response) => { response.writeHead(204); response.end(); });
  await new Promise(resolve => target.listen(0, '127.0.0.1', resolve));
  t.after(() => target.close());
  const targetPort = target.address().port;

  const proxy = net.createServer(client => {
    let state = 0;
    client.on('data', chunk => {
      if (state === 0) { state = 1; client.write(Buffer.from([5, 0])); return; }
      if (state === 1) {
        state = 2;
        const upstream = net.connect({ host: '127.0.0.1', port: targetPort }, () => {
          client.write(Buffer.from([5, 0, 0, 1, 127, 0, 0, 1, targetPort >> 8, targetPort & 255]));
          client.pipe(upstream); upstream.pipe(client);
        });
        upstream.on('error', error => client.destroy(error));
      }
    });
  });
  await new Promise(resolve => proxy.listen(0, '127.0.0.1', resolve));
  t.after(() => proxy.close());

  const result = await realPathProbe(proxy.address().port, { host: 'probe.local', port: targetPort, path: '/', tls: false }, { timeoutMs: 1500 });
  assert.equal(result.ok, true); assert.equal(result.status, 204); assert.ok(result.totalMs >= 0);
});
