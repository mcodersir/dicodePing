const DEFAULT_SUB = 'https://raw.githubusercontent.com/mcodersir/DicodeConfigChecker/refs/heads/main/sub.txt';
const state = { profiles: [], results: [], selected: null, connected: false, scanning: false };
const $ = selector => document.querySelector(selector);
const fa = value => new Intl.NumberFormat('fa-IR').format(value);
const escapeHtml = value => String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));

function toast(message) { const el = $('#toast'); el.textContent = message; el.classList.add('show'); setTimeout(() => el.classList.remove('show'), 3200); }
function updateCount() { $('#profile-count').textContent = `${fa(state.profiles.length)} کانفیگ`; $('#connect-button').disabled = !state.selected; }
function selectProfile(profile) { state.selected = profile; renderServers('#client-list', state.results.length ? state.results : state.profiles.map(profile => ({ profile }))); updateCount(); }

function renderServers(target, rows) {
  const el = $(target);
  if (!rows.length) { el.className = 'server-list empty'; el.textContent = 'موردی برای نمایش وجود ندارد.'; return; }
  el.className = 'server-list';
  el.innerHTML = rows.map(row => {
    const p = row.profile || row;
    return `<div class="server ${state.selected?.id === p.id ? 'selected' : ''}" data-id="${p.id}"><div class="server-name"><b>${escapeHtml(p.name)}</b><small>${escapeHtml(p.protocol.toUpperCase())} · ${escapeHtml(p.host)}:${p.port}</small></div><span class="latency">${row.medianMs == null ? '—' : `${fa(row.medianMs)} ms`}</span><span class="loss">${row.lossPercent == null ? '—' : `${fa(row.lossPercent)}٪ loss`}</span><span class="score ${row.ok === false ? 'bad' : ''}">${row.score == null ? 'جدید' : fa(row.score)}</span></div>`;
  }).join('');
  el.querySelectorAll('.server').forEach(node => node.addEventListener('click', () => selectProfile(state.profiles.find(p => p.id === node.dataset.id))));
}

function addProfiles(profiles) {
  const map = new Map(state.profiles.map(p => [p.id, p])); profiles.forEach(p => map.set(p.id, p)); state.profiles = [...map.values()];
  if (!state.selected && state.profiles.length) state.selected = state.profiles[0];
  renderServers('#client-list', state.profiles.map(profile => ({ profile }))); updateCount();
}

async function importText() {
  const parsed = await window.dicode.parse($('#config-input').value);
  addProfiles(parsed.profiles); toast(`${fa(parsed.profiles.length)} کانفیگ اضافه شد${parsed.errors.length ? `؛ ${fa(parsed.errors.length)} نامعتبر` : ''}`);
}

async function sync(url) {
  try { toast('در حال دریافت ساب…'); const result = await window.dicode.fetchSubscription(url); addProfiles(result.profiles); toast(`${fa(result.profiles.length)} کانفیگ همگام شد`); return result; }
  catch (error) { toast(`خطای ساب: ${error.message}`); throw error; }
}

async function scan() {
  if (!state.profiles.length || state.scanning) return;
  state.scanning = true; $('#scan-button').disabled = true; $('#cancel-button').disabled = false; $('#scan-list').className = 'server-list'; $('#scan-list').innerHTML = '';
  try {
    state.results = await window.dicode.scan(state.profiles);
    renderServers('#scan-list', state.results); renderServers('#client-list', state.results);
    const best = state.results.find(x => x.ok); if (best) selectProfile(best.profile);
    toast('اسکن واقعی کامل شد');
  } catch (error) { toast(`اسکن متوقف شد: ${error.message}`); }
  finally { state.scanning = false; $('#scan-button').disabled = false; $('#cancel-button').disabled = true; }
}

window.dicode.onProgress(({ done, total, row }) => {
  const percent = Math.round(done / total * 100); $('#tested-count').textContent = fa(done); $('#scan-progress').textContent = `${fa(percent)}٪`; $('#meter-bar').style.width = `${percent}%`;
  const current = [...document.querySelectorAll('#scan-list .server')];
  const holder = document.createElement('div'); holder.innerHTML = `<div class="server"><div class="server-name"><b>${escapeHtml(row.profile.name)}</b><small>${escapeHtml(row.profile.protocol.toUpperCase())} · ${escapeHtml(row.profile.host)}</small></div><span class="latency">${row.medianMs == null ? '—' : `${fa(row.medianMs)} ms`}</span><span class="loss">${fa(row.lossPercent)}٪ loss</span><span class="score ${row.ok ? '' : 'bad'}">${fa(row.score)}</span></div>`; $('#scan-list').append(holder.firstElementChild);
  const alive = document.querySelectorAll('#scan-list .score:not(.bad)').length; $('#alive-count').textContent = fa(alive);
  const pings = state.results.map(x => x.medianMs).filter(Number.isFinite); if (row.medianMs != null) pings.push(row.medianMs); $('#best-ping').textContent = pings.length ? `${fa(Math.min(...pings))} ms` : '—';
});

document.querySelectorAll('.nav').forEach(button => button.addEventListener('click', () => { document.querySelectorAll('.nav,.page').forEach(x => x.classList.remove('active')); button.classList.add('active'); $(`#${button.dataset.page}`).classList.add('active'); $('#page-title').textContent = button.querySelector('span').textContent; }));
$('#import-button').addEventListener('click', importText); $('#scan-button').addEventListener('click', async () => { await importText(); scan(); }); $('#quick-scan').addEventListener('click', scan); $('#cancel-button').addEventListener('click', () => window.dicode.cancelScan());
$('#sync-default').addEventListener('click', async () => { await sync(DEFAULT_SUB); scan(); }); $('#sync-custom').addEventListener('click', () => sync($('#sub-url').value));
$('#connect-button').addEventListener('click', async () => {
  try {
    if (state.connected) { await window.dicode.disconnect(); state.connected = false; $('#connect-button').textContent = 'اتصال'; $('.hero').classList.remove('connected'); $('#connection-title').textContent = 'آماده اتصال'; }
    else { const result = await window.dicode.connect(state.selected); state.connected = true; $('#connect-button').textContent = 'قطع اتصال'; $('.hero').classList.add('connected'); $('#connection-title').textContent = 'متصل'; $('#connection-detail').textContent = `${state.selected.name} · SOCKS ${result.socks}`; }
  } catch (error) { toast(`خطای اتصال: ${error.message}`); }
});
updateCount();
