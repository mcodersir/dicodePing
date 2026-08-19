import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('dicode', Object.freeze({
  parse: text => ipcRenderer.invoke('profiles:parse', text),
  fetchSubscription: url => ipcRenderer.invoke('subscription:fetch', url),
  scan: profiles => ipcRenderer.invoke('scan:start', profiles),
  cancelScan: () => ipcRenderer.invoke('scan:cancel'),
  connect: profile => ipcRenderer.invoke('client:connect', profile),
  disconnect: () => ipcRenderer.invoke('client:disconnect'),
  onProgress: listener => { const handler = (_, value) => listener(value); ipcRenderer.on('scan:progress', handler); return () => ipcRenderer.off('scan:progress', handler); }
}));
