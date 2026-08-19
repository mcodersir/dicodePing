import { app, BrowserWindow, ipcMain, shell } from 'electron';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseProfileList } from '../core/profiles.mjs';
import { fetchSubscription } from '../core/subscription.mjs';
import { createClientConfig } from '../core/xray-config.mjs';
import { scanWithXray } from './scan-host.mjs';
import { startXray } from './xray-supervisor.mjs';

const root = path.dirname(fileURLToPath(import.meta.url));
let window, activeRuntime, scanAbort;

function send(channel, payload) { if (window && !window.isDestroyed()) window.webContents.send(channel, payload); }

function createWindow() {
  window = new BrowserWindow({ width: 1240, height: 800, minWidth: 900, minHeight: 620, backgroundColor: '#07111f', title: 'DicodePing 3', webPreferences: { preload: path.join(root, 'preload.mjs'), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  window.loadFile(path.join(root, '..', 'ui', 'index.html'));
}

ipcMain.handle('profiles:parse', (_, text) => parseProfileList(text));
ipcMain.handle('subscription:fetch', (_, url) => fetchSubscription(url));
ipcMain.handle('scan:start', async (_, profiles) => {
  scanAbort?.abort(); scanAbort = new AbortController();
  return scanWithXray(profiles, { signal: scanAbort.signal, onProgress: value => send('scan:progress', value) });
});
ipcMain.handle('scan:cancel', () => { scanAbort?.abort(); return true; });
ipcMain.handle('client:connect', async (_, profile) => {
  if (activeRuntime) await activeRuntime.stop();
  activeRuntime = await startXray(createClientConfig(profile), 2080);
  return { connected: true, socks: '127.0.0.1:2080', http: '127.0.0.1:2081' };
});
ipcMain.handle('client:disconnect', async () => { await activeRuntime?.stop(); activeRuntime = null; return { connected: false }; });
ipcMain.handle('external:open', (_, url) => { const parsed = new URL(url); if (parsed.protocol === 'https:') return shell.openExternal(parsed.href); });

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
app.on('before-quit', event => { if (activeRuntime) { event.preventDefault(); activeRuntime.stop().finally(() => { activeRuntime = null; app.quit(); }); } });
