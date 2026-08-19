import { spawn } from 'node:child_process';
import { access, mkdtemp, rm, writeFile } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';

async function exists(value) { try { await access(value); return true; } catch { return false; } }

export async function locateXray({ resourcesPath = process.resourcesPath, env = process.env } = {}) {
  const exe = process.platform === 'win32' ? 'xray.exe' : 'xray';
  const candidates = [env.DICODE_XRAY, resourcesPath && path.join(resourcesPath, 'runtime', exe), path.join(process.cwd(), 'runtime', exe)].filter(Boolean);
  for (const candidate of candidates) if (await exists(candidate)) return candidate;
  return exe;
}

export async function waitForPort(port, timeoutMs = 5000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const ok = await new Promise(resolve => {
      const socket = net.connect({ host: '127.0.0.1', port });
      socket.once('connect', () => { socket.destroy(); resolve(true); });
      socket.once('error', () => resolve(false));
      socket.setTimeout(250, () => { socket.destroy(); resolve(false); });
    });
    if (ok) return;
    await new Promise(resolve => setTimeout(resolve, 80));
  }
  throw new Error(`Xray did not open port ${port}`);
}

export async function startXray(config, readyPort, options = {}) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'dicodeping-'));
  const configPath = path.join(directory, 'config.json');
  await writeFile(configPath, JSON.stringify(config), { encoding: 'utf8', mode: 0o600 });
  const binary = options.binary || await locateXray(options);
  const child = spawn(binary, ['run', '-config', configPath], { stdio: ['ignore', 'ignore', 'pipe'], windowsHide: true });
  let stderr = '';
  child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-12000); });
  try { await waitForPort(readyPort, options.startupTimeoutMs || 6000); }
  catch (error) { child.kill(); await rm(directory, { recursive: true, force: true }); throw new Error(`${error.message}: ${stderr.trim()}`); }
  return {
    pid: child.pid,
    stderr: () => stderr,
    async stop() {
      if (!child.killed) child.kill('SIGTERM');
      await Promise.race([new Promise(resolve => child.once('exit', resolve)), new Promise(resolve => setTimeout(resolve, 1500))]);
      if (child.exitCode == null) child.kill('SIGKILL');
      await rm(directory, { recursive: true, force: true });
    }
  };
}
