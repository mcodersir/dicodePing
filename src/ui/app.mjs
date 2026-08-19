const DEFAULT_SUB = 'https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt';
const STORAGE_KEY = 'dicode.customSubscriptions.v3';
const $ = selector => document.querySelector(selector);
const fa = value => new Intl.NumberFormat('fa-IR').format(value);
const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));

const state = {
  profiles: [], resultById: new Map(), selected: null, connected: false, scanning: false,
  activeSource: 'all', query: '', sources: new Map()
};

function sourceId(url) {
  let hash = 2166136261;
  for (const char of url) { hash ^= char.charCodeAt(0); hash = Math.imul(hash, 16777619); }
  return `sub-${(hash >>> 0).toString(16)}`;
}

function savedUrls() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]').filter(value => typeof value === 'string'); }
  catch { return []; }
}

function persistSources() {
  const urls = [...state.sources.values()].filter(source => !source.primary).map(source => source.url);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(urls));
}

function createSource(url, { primary = false, name } = {}) {
  let hostname = 'Subscription';
  try { hostname = new URL(url).hostname.replace(/^www\./, ''); } catch { /* validated by backend */ }
  const source = { id: primary ? 'primary' : sourceId(url), url, primary, name: name || hostname, status: 'idle', count: 0 };
  state.sources.set(source.id, source);
  return source;
}

createSource(DEFAULT_SUB, { primary: true, name: 'Dicode Config Checker' });
savedUrls().forEach(url => createSource(url));

let toastTimer;
function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3300);
}

function setSyncState(text, mode = '') {
  const el = $('#sync-state');
  el.className = `sync-state ${mode}`.trim();
  el.querySelector('span').textContent = text;
}

function rowsForDisplay() {
  const query = state.query.trim().toLowerCase();
  return state.profiles
    .filter(profile => state.activeSource === 'all' || profile._sourceIds?.includes(state.activeSource))
    .filter(profile => !query || `${profile.name} ${profile.host} ${profile.protocol}`.toLowerCase().includes(query))
    .map(profile => state.resultById.get(profile.id) || { profile });
}

function updateMetrics() {
  const results = [...state.resultById.values()];
  const alive = results.filter(row => row.ok);
  const best = alive.map(row => row.medianMs).filter(Number.isFinite).sort((a, b) => a - b)[0];
  $('#profile-count').textContent = `${fa(state.profiles.length)} کانفیگ`;
  $('#metric-total').textContent = fa(state.profiles.length);
  $('#metric-alive').textContent = results.length ? fa(alive.length) : '—';
  $('#metric-best').textContent = Number.isFinite(best) ? `${fa(best)} ms` : '—';
  $('#connect-button').disabled = !state.selected || state.scanning;
  $('#status-selected').textContent = state.selected ? `انتخاب: ${state.selected.name}` : 'کانفیگی انتخاب نشده';
}

function renderServers(target, rows = rowsForDisplay()) {
  const el = $(target);
  if (!rows.length) {
    el.className = 'server-list empty-state';
    el.innerHTML = '<span class="empty-icon">⌁</span><b>موردی برای نمایش نیست</b><small>ساب‌ها را همگام کنید یا فیلتر جست‌وجو را تغییر دهید.</small>';
    return;
  }
  el.className = 'server-list';
  el.innerHTML = rows.map(row => {
    const profile = row.profile || row;
    const protocol = String(profile.protocol || 'config').toUpperCase();
    const protocolMark = protocol.slice(0, 2);
    const scoreClass = row.score == null ? 'new' : row.ok === false ? 'bad' : '';
    const sourceName = profile._sourceIds?.map(id => state.sources.get(id)?.name).filter(Boolean)[0] || 'ورودی دستی';
    return `<div class="server ${state.selected?.id === profile.id ? 'selected' : ''}" data-id="${escapeHtml(profile.id)}">
      <div class="server-name"><span class="protocol-mark">${escapeHtml(protocolMark)}</span><div class="server-copy"><b>${escapeHtml(profile.name)}</b><small>${escapeHtml(profile.host)}:${escapeHtml(profile.port)} · ${escapeHtml(sourceName)}</small></div></div>
      <span class="protocol-cell">${escapeHtml(protocol)}</span>
      <span class="latency">${row.medianMs == null ? '—' : `${fa(row.medianMs)} ms`}</span>
      <span class="loss">${row.lossPercent == null ? '—' : `${fa(row.lossPercent)}%`}</span>
      <span class="score ${scoreClass}">${row.score == null ? 'جدید' : fa(row.score)}</span>
    </div>`;
  }).join('');
  el.querySelectorAll('.server').forEach(node => node.addEventListener('click', () => selectProfile(state.profiles.find(profile => profile.id === node.dataset.id))));
}

function renderSourceNavigation() {
  const tabs = $('#source-tabs');
  const entries = [...state.sources.values()];
  tabs.innerHTML = `<button class="source-tab ${state.activeSource === 'all' ? 'active' : ''}" data-source="all">همه · ${fa(state.profiles.length)}</button>` + entries.map(source =>
    `<button class="source-tab ${state.activeSource === source.id ? 'active' : ''}" data-source="${source.id}">${escapeHtml(source.name)} · ${fa(source.count)}</button>`
  ).join('');
  tabs.querySelectorAll('.source-tab').forEach(button => button.addEventListener('click', () => {
    state.activeSource = button.dataset.source;
    renderSourceNavigation();
    renderServers('#client-list');
  }));

  $('#source-list').innerHTML = entries.map(source => `<article class="source-card">
    <span class="source-logo">${source.primary ? 'DP' : 'SUB'}</span>
    <div><b>${escapeHtml(source.name)}${source.primary ? ' · پیش‌فرض' : ''}</b><small>${escapeHtml(source.url)}</small></div>
    <button class="icon-button" data-sync-source="${source.id}" title="همگام‌سازی"><svg viewBox="0 0 24 24"><path d="M5 12a7 7 0 0 1 12-4.9L19 9m0-5v5h-5M19 12a7 7 0 0 1-12 4.9L5 15m0 5v-5h5"/></svg></button>
    <span class="source-meta"><i></i>${source.status === 'error' ? 'خطا' : source.status === 'syncing' ? 'در حال دریافت' : `${fa(source.count)} کانفیگ`}</span>
  </article>`).join('');
  document.querySelectorAll('[data-sync-source]').forEach(button => button.addEventListener('click', () => syncSource(state.sources.get(button.dataset.syncSource))));
}

function selectProfile(profile) {
  if (!profile) return;
  state.selected = profile;
  renderServers('#client-list');
  if ($('#scan-list').classList.contains('server-list') && state.resultById.size) renderServers('#scan-list', [...state.resultById.values()]);
  updateMetrics();
}

function addProfiles(profiles, sourceIdValue = 'manual') {
  const map = new Map(state.profiles.map(profile => [profile.id, profile]));
  for (const raw of profiles) {
    const current = map.get(raw.id);
    const ids = new Set([...(current?._sourceIds || []), sourceIdValue]);
    map.set(raw.id, { ...current, ...raw, _sourceIds: [...ids] });
  }
  state.profiles = [...map.values()];
  if (!state.selected && state.profiles.length) state.selected = state.profiles[0];
  for (const source of state.sources.values()) source.count = state.profiles.filter(profile => profile._sourceIds?.includes(source.id)).length;
  renderSourceNavigation();
  renderServers('#client-list');
  updateMetrics();
}

async function importText() {
  const text = $('#config-input').value.trim();
  if (!text) { toast('ابتدا کانفیگ یا subscription را وارد کنید'); return { profiles: [] }; }
  const parsed = await window.dicode.parse(text);
  addProfiles(parsed.profiles);
  toast(`${fa(parsed.profiles.length)} کانفیگ اضافه شد${parsed.errors.length ? `؛ ${fa(parsed.errors.length)} ورودی نامعتبر` : ''}`);
  return parsed;
}

async function syncSource(source, { announce = true } = {}) {
  if (!source) return null;
  source.status = 'syncing';
  renderSourceNavigation();
  setSyncState('در حال همگام‌سازی', 'loading');
  try {
    const result = await window.dicode.fetchSubscription(source.url);
    addProfiles(result.profiles, source.id);
    source.status = 'ready';
    source.count = result.profiles.length;
    renderSourceNavigation();
    if (announce) toast(`${fa(result.profiles.length)} کانفیگ از ${source.name} دریافت شد`);
    return result;
  } catch (error) {
    source.status = 'error';
    renderSourceNavigation();
    if (announce) toast(`خطای ${source.name}: ${error.message}`);
    return null;
  } finally {
    const hasError = [...state.sources.values()].some(item => item.status === 'error');
    setSyncState(hasError ? 'برخی منابع خطا دارند' : 'همگام', hasError ? 'error' : '');
  }
}

async function syncAll({ announce = true } = {}) {
  setSyncState('دریافت همه ساب‌ها', 'loading');
  const results = await Promise.all([...state.sources.values()].map(source => syncSource(source, { announce: false })));
  const received = results.filter(Boolean).reduce((sum, result) => sum + result.profiles.length, 0);
  if (announce) toast(`${fa(received)} پروفایل از همه subscriptionها همگام شد`);
  return received;
}

function chooseBest() {
  return [...state.resultById.values()].filter(row => row.ok).sort((a, b) => (b.score ?? 0) - (a.score ?? 0) || (a.medianMs ?? Infinity) - (b.medianMs ?? Infinity))[0];
}

async function scan() {
  if (!state.profiles.length || state.scanning) return [];
  state.scanning = true;
  state.resultById.clear();
  $('#scan-button').disabled = true;
  $('#quick-scan').disabled = true;
  $('#cancel-button').disabled = false;
  $('#auto-connect').disabled = true;
  $('#scan-list').className = 'server-list';
  $('#scan-list').innerHTML = '';
  $('#tested-count').textContent = '۰';
  $('#alive-count').textContent = '۰';
  $('#best-ping').textContent = '—';
  $('#scan-progress').textContent = '۰٪';
  $('#meter-bar').style.width = '0%';
  setSyncState('اسکن واقعی', 'loading');
  try {
    const results = await window.dicode.scan(state.profiles);
    results.forEach(row => state.resultById.set(row.profile.id, row));
    renderServers('#scan-list', results);
    renderServers('#client-list');
    const best = chooseBest();
    if (best) selectProfile(state.profiles.find(profile => profile.id === best.profile.id) || best.profile);
    toast('اسکن واقعی همه کانفیگ‌ها کامل شد');
    return results;
  } catch (error) {
    toast(`اسکن متوقف شد: ${error.message}`);
    return [];
  } finally {
    state.scanning = false;
    $('#scan-button').disabled = false;
    $('#quick-scan').disabled = false;
    $('#cancel-button').disabled = true;
    $('#auto-connect').disabled = false;
    setSyncState('آماده');
    updateMetrics();
  }
}

async function connectProfile(profile) {
  if (!profile) return;
  const result = await window.dicode.connect(profile);
  state.connected = true;
  state.selected = profile;
  $('.connection-card').classList.add('connected');
  $('#connection-title').textContent = 'اتصال برقرار است';
  $('#connection-detail').textContent = `${profile.name} · SOCKS ${result.socks}`;
  $('#connect-button span').textContent = 'قطع اتصال';
  $('#auto-connect').classList.add('connected');
  $('#auto-connect span').textContent = 'قطع اتصال';
  updateMetrics();
}

async function disconnect() {
  await window.dicode.disconnect();
  state.connected = false;
  $('.connection-card').classList.remove('connected');
  $('#connection-title').textContent = 'آماده اتصال';
  $('#connection-detail').textContent = 'بهترین مسیر را خودکار پیدا کنید یا یک کانفیگ انتخاب کنید.';
  $('#connect-button span').textContent = 'اتصال به انتخاب‌شده';
  $('#auto-connect').classList.remove('connected');
  $('#auto-connect span').textContent = 'اتصال هوشمند';
}

async function toggleSelectedConnection() {
  try { if (state.connected) await disconnect(); else await connectProfile(state.selected); }
  catch (error) { toast(`خطای اتصال: ${error.message}`); }
}

async function autoConnect() {
  if (state.connected) { await toggleSelectedConnection(); return; }
  const button = $('#auto-connect');
  button.disabled = true;
  button.querySelector('span').textContent = 'یافتن بهترین…';
  try {
    if (!state.profiles.length) await syncAll({ announce: false });
    if (!state.profiles.length) throw new Error('هیچ کانفیگی دریافت نشد');
    if (!state.resultById.size) await scan();
    const best = chooseBest();
    if (!best) throw new Error('مسیر پاسخ‌گویی پیدا نشد');
    const profile = state.profiles.find(item => item.id === best.profile.id) || best.profile;
    selectProfile(profile);
    await connectProfile(profile);
    toast(`اتصال خودکار به بهترین مسیر: ${profile.name}`);
  } catch (error) { toast(`اتصال هوشمند ناموفق بود: ${error.message}`); }
  finally { button.disabled = false; if (!state.connected) button.querySelector('span').textContent = 'اتصال هوشمند'; }
}

window.dicode.onProgress(({ done, total, row }) => {
  state.resultById.set(row.profile.id, row);
  const percent = total ? Math.round(done / total * 100) : 0;
  $('#tested-count').textContent = fa(done);
  $('#scan-progress').textContent = `${fa(percent)}٪`;
  $('#meter-bar').style.width = `${percent}%`;
  renderServers('#scan-list', [...state.resultById.values()]);
  renderServers('#client-list');
  const alive = [...state.resultById.values()].filter(result => result.ok);
  $('#alive-count').textContent = fa(alive.length);
  const pings = alive.map(result => result.medianMs).filter(Number.isFinite);
  $('#best-ping').textContent = pings.length ? `${fa(Math.min(...pings))} ms` : '—';
  updateMetrics();
});

document.querySelectorAll('.nav').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.nav,.page').forEach(element => element.classList.remove('active'));
  button.classList.add('active');
  $(`#${button.dataset.page}`).classList.add('active');
  $('#page-title').textContent = button.dataset.title;
  $('#page-subtitle').textContent = button.dataset.subtitle;
}));

$('#profile-search').addEventListener('input', event => { state.query = event.target.value; renderServers('#client-list'); });
$('#import-button').addEventListener('click', importText);
$('#scan-button').addEventListener('click', async () => { const parsed = await importText(); if (parsed.profiles.length) await scan(); });
$('#quick-scan').addEventListener('click', scan);
$('#cancel-button').addEventListener('click', () => window.dicode.cancelScan());
$('#sync-default').addEventListener('click', () => syncAll());
$('#refresh-all').addEventListener('click', () => syncAll());
$('#connect-button').addEventListener('click', toggleSelectedConnection);
$('#auto-connect').addEventListener('click', autoConnect);
$('#sync-custom').addEventListener('click', async () => {
  const url = $('#sub-url').value.trim();
  if (!url) { toast('آدرس subscription را وارد کنید'); return; }
  const source = state.sources.get(sourceId(url)) || createSource(url);
  persistSources();
  renderSourceNavigation();
  const result = await syncSource(source);
  if (result) $('#sub-url').value = '';
});

async function bootstrap() {
  renderSourceNavigation();
  updateMetrics();
  await syncAll({ announce: false });
  if (!state.profiles.length) {
    $('#client-list').className = 'server-list empty-state';
    $('#client-list').innerHTML = '<span class="empty-icon">!</span><b>کانفیگی دریافت نشد</b><small>اتصال اینترنت یا آدرس subscription را بررسی کنید.</small>';
  } else {
    toast(`${fa(state.profiles.length)} کانفیگ از تمام ساب‌ها آماده است`);
  }
}

bootstrap();
