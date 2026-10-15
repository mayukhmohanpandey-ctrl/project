'use strict';

/* ------------------------------------------------------------------ constants */
const DIMENSIONS = [
  { key: 'clarity',     label: 'Clarity',       hint: 'One clear task, no ambiguity.' },
  { key: 'context',     label: 'Context',       hint: 'Who it is for and why.' },
  { key: 'constraints', label: 'Constraints',   hint: 'Length, tone, scope, limits.' },
  { key: 'format',      label: 'Output format', hint: 'The shape of the answer.' },
  { key: 'role',        label: 'Role',          hint: 'Who the assistant should be.' },
  { key: 'examples',    label: 'Examples',      hint: 'A sample of what good looks like.' },
  { key: 'reasoning',   label: 'Reasoning',     hint: 'Steps to think through first.' },
  { key: 'guardrails',  label: 'Guardrails',    hint: 'What to avoid or never invent.' },
];
const REFINEMENTS = [
  ['shorter', 'Shorter'], ['detailed', 'More detailed'], ['formal', 'More formal'],
  ['friendly', 'Friendlier'], ['examples', 'Add examples'], ['simpler', 'Simpler'],
];
const MODES = ['general', 'writing', 'coding', 'analysis', 'image'];
const TARGETS = ['any', 'chatgpt', 'claude', 'gemini', 'local'];
const MAX_PROMPT = 4000, MAX_TEXT = 12000;
const HISTORY_KEY = 'sharpen.history.v1', HISTORY_MAX = 12, THEME_KEY = 'sharpen.theme';
const PLACEHOLDER = /\[([A-Z][A-Z0-9 _\/-]{1,40})\]/g;

/* ------------------------------------------------------------------ tiny helpers */
const $ = id => document.getElementById(id);
function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const el = {
  prompt: $('prompt'), mode: $('mode'), target: $('target'), count: $('count'),
  sharpen: $('sharpenBtn'), cancel: $('cancelBtn'), error: $('error'),
  empty: $('emptyState'), result: $('result'), title: $('resultTitle'), versions: $('versions'),
  out: $('outText'), skeleton: $('skeleton'), blanks: $('blanks'), blanksSummary: $('blanksSummary'), blankGrid: $('blankGrid'),
  changes: $('changes'), diff: $('diffText'), diffNote: $('diffNote'),
  compareBtn: $('compareBtn'), compareOut: $('compareOut'), ansA: $('ansA'), ansB: $('ansB'),
  refine: $('refine'), scoreLine: $('scoreLine'), track: $('track'), rubric: $('rubric'),
  gapsWrap: $('gapsWrap'), gaps: $('gaps'), toast: $('toast'),
};

const state = {
  prompt: '', mode: 'general', target: 'any',
  result: null,              // { title, score, rubric, gaps, changes }
  versions: [],              // [{ label, text }]
  v: 0,                      // index of the visible version
  fills: {},                 // placeholder name -> value
  busy: false, controller: null, cancelled: false,
};
const current = () => state.versions[state.v];
const applyFills = text => text.replace(PLACEHOLDER, (m, k) => (state.fills[k] || '').trim() || m);

/* ------------------------------------------------------------------ toast, errors */
let toastTimer;
function toast(msg) {
  el.toast.textContent = msg;
  el.toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.toast.classList.remove('show'), 1800);
}
function showError(msg) { el.error.textContent = msg; el.error.hidden = false; }
function clearError() { el.error.hidden = true; el.error.textContent = ''; }

/* ------------------------------------------------------------------ api */
async function api(path, body, signal) {
  let res;
  try {
    res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new Error('Cannot reach the server. Check your connection and try again.');
  }
  let data = {};
  try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status}).`);
  return data;
}
async function run(task) {
  if (state.busy) return;
  state.busy = true; state.cancelled = false;
  const controller = state.controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 100000);
  setBusy(true);
  try { await task(controller.signal); }
  catch (e) {
    if (e.name === 'AbortError') showError(state.cancelled ? 'Cancelled.' : 'The request timed out. Try again.');
    else showError(e.message);
  } finally {
    clearTimeout(timer);
    state.busy = false; state.controller = null;
    setBusy(false);
  }
}
function setBusy(b) {
  el.sharpen.disabled = b;
  el.cancel.hidden = !b;
  document.querySelectorAll('.refine .chip, #compareBtn, #copyBtn, #shareBtn, #downloadBtn').forEach(x => (x.disabled = b));
}

/* ------------------------------------------------------------------ input */
function autosize() {
  el.prompt.style.height = 'auto';
  el.prompt.style.height = Math.min(340, Math.max(118, el.prompt.scrollHeight + 2)) + 'px';
}
function updateCount() {
  const n = el.prompt.value.length;
  el.count.textContent = `${n} / ${MAX_PROMPT}`;
  el.count.classList.toggle('warn', n > MAX_PROMPT * 0.9);
}
el.prompt.addEventListener('input', () => { updateCount(); autosize(); });
el.prompt.addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sharpen(); }
});
$('samples').addEventListener('click', e => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  el.prompt.value = chip.dataset.text; el.mode.value = chip.dataset.mode;
  updateCount(); autosize(); el.prompt.focus();
});
el.sharpen.addEventListener('click', sharpen);
el.cancel.addEventListener('click', () => { state.cancelled = true; state.controller && state.controller.abort(); });

/* ------------------------------------------------------------------ actions */
function sharpen() {
  if (state.busy) return;
  const prompt = el.prompt.value.trim();
  if (!prompt) { showError('Type or paste a prompt first.'); el.prompt.focus(); return; }
  if (prompt.length > MAX_PROMPT) { showError(`That prompt is too long. The limit is ${MAX_PROMPT} characters.`); return; }
  clearError();
  const previous = { result: state.result, versions: state.versions, v: state.v };

  // loading view
  el.empty.hidden = true; el.result.hidden = false;
  el.skeleton.hidden = false; el.out.hidden = true; el.blanks.hidden = true;
  el.title.textContent = 'Sharpening your prompt';
  el.versions.replaceChildren();
  setTab('prompt');

  return run(async signal => {
    try {
      const data = await api('/api/sharpen', { prompt, mode: el.mode.value, target: el.target.value }, signal);
      const result = validateResult(data);
      if (!result) throw new Error('The server sent a result the page could not read. Try again.');
      Object.assign(state, { prompt, mode: el.mode.value, target: el.target.value, fills: {} });
      loadResult(result, [{ label: 'Sharpened', text: result.sharpened }]);
      pushHistory();
      if (!reducedMotion()) el.result.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (e) {
      // put back whatever was on screen before
      Object.assign(state, previous);
      if (state.result) renderAll(false); else { el.result.hidden = true; el.empty.hidden = false; }
      el.skeleton.hidden = true; el.out.hidden = false;
      throw e;
    }
  });
}

function refine(instruction, label) {
  if (!state.result) return;
  clearError();
  return run(async signal => {
    const data = await api('/api/refine', {
      text: current().text, instruction, mode: state.mode, target: state.target,
    }, signal);
    if (typeof data.text !== 'string' || !data.text.trim()) throw new Error('The model sent an empty revision. Try again.');
    state.versions = state.versions.slice(0, state.v + 1);
    state.versions.push({ label, text: data.text.slice(0, MAX_TEXT) });
    state.v = state.versions.length - 1;
    renderAll(true);
    pushHistory();
    toast(`${label} applied`);
  });
}

function compare() {
  if (!state.result) return;
  clearError();
  el.compareOut.hidden = true;
  el.compareBtn.textContent = 'Running both prompts';
  return run(async signal => {
    try {
      const data = await api('/api/compare', { original: state.prompt, sharpened: applyFills(current().text) }, signal);
      el.ansA.textContent = String(data.original || '(no answer)');
      el.ansB.textContent = String(data.sharpened || '(no answer)');
      el.compareOut.hidden = false;
    } finally {
      el.compareBtn.textContent = 'Run both prompts';
    }
  });
}
el.compareBtn.addEventListener('click', compare);

/* ------------------------------------------------------------------ result model */
function validateResult(r) {
  if (!r || typeof r !== 'object') return null;
  const text = typeof r.sharpened === 'string' ? r.sharpened.trim().slice(0, MAX_TEXT) : '';
  if (!text) return null;
  const lvl = v => Math.max(0, Math.min(3, Math.round(Number(v) || 0)));
  const pct = v => Math.max(0, Math.min(100, Math.round(Number(v) || 0)));
  const list = v => (Array.isArray(v) ? v.filter(s => typeof s === 'string' && s.trim()).map(s => s.slice(0, 300)).slice(0, 6) : []);
  const rubric = {};
  for (const d of DIMENSIONS) {
    const row = (r.rubric && r.rubric[d.key]) || {};
    rubric[d.key] = { before: lvl(row.before), after: lvl(row.after) };
  }
  return {
    sharpened: text,
    title: typeof r.title === 'string' && r.title.trim() ? r.title.trim().slice(0, 80) : 'Sharpened prompt',
    score: { before: pct(r.score && r.score.before), after: pct(r.score && r.score.after) },
    rubric, gaps: list(r.gaps), changes: list(r.changes),
  };
}
function loadResult(result, versions) {
  state.result = result; state.versions = versions; state.v = 0;
  el.skeleton.hidden = true; el.out.hidden = false;
  renderAll(true);
}

/* ------------------------------------------------------------------ rendering */
function renderAll(animateScore) {
  const r = state.result;
  el.empty.hidden = true; el.result.hidden = false;
  el.title.textContent = r.title;
  renderVersions(); renderOut(); renderBlanks(); renderRedline(); renderMargin(animateScore);
  el.compareOut.hidden = true;
}

function renderVersions() {
  el.versions.replaceChildren();
  if (state.versions.length < 2) return;
  state.versions.forEach((ver, i) => {
    el.versions.append(h('button', {
      type: 'button', class: 'vpill', 'aria-pressed': String(i === state.v), text: `v${i + 1} ${ver.label}`,
      onclick: () => { state.v = i; renderAll(false); },
    }));
  });
}

// Fill placeholders inside one chunk of text, appending nodes to parent.
function appendWithBlanks(parent, text) {
  let last = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    parent.append(text.slice(last, m.index));
    const val = (state.fills[m[1]] || '').trim();
    parent.append(h('span', { class: val ? 'filled' : 'ph', text: val || m[0] }));
    last = m.index + m[0].length;
  }
  parent.append(text.slice(last));
}

// Split "<tag>body</tag>" blocks into sections. Returns null when the prompt has no tags.
function parseSections(text) {
  const re = /<([a-z][a-z0-9_-]*)>\n?([\s\S]*?)\n?<\/\1>/gi;
  const out = []; let last = 0, m;
  while ((m = re.exec(text))) {
    if (text.slice(last, m.index).trim()) out.push({ tag: '', body: text.slice(last, m.index).trim() });
    out.push({ tag: m[1], body: m[2].trim() });
    last = m.index + m[0].length;
  }
  if (!out.some(x => x.tag)) return null;
  if (text.slice(last).trim()) out.push({ tag: '', body: text.slice(last).trim() });
  return out;
}

function renderOut() {
  const text = current().text;
  el.out.replaceChildren();
  const sections = parseSections(text);
  if (!sections) { appendWithBlanks(el.out, text); return; }
  for (const sec of sections) {
    const box = h('section', { class: 'sec' + (sec.tag ? ' sec-' + sec.tag.toLowerCase().replace(/[^a-z0-9]+/g, '-') : '') });
    if (sec.tag) box.append(h('h4', { class: 'sec-label', text: sec.tag.replace(/[_-]+/g, ' ') }));
    const body = h('div', { class: 'sec-body' });
    appendWithBlanks(body, sec.body);
    box.append(body);
    el.out.append(box);
  }
}

function renderBlanks() {
  const keys = [...new Set([...current().text.matchAll(PLACEHOLDER)].map(m => m[1]))];
  el.blankGrid.replaceChildren();
  el.blanks.hidden = keys.length === 0;
  if (!keys.length) return;
  el.blanksSummary.textContent = `Fill in the blanks (${keys.length})`;
  keys.forEach((k, i) => {
    const id = `blank-${i}`;
    const input = h('input', { id, type: 'text', value: state.fills[k] || '', autocomplete: 'off', maxlength: '200' });
    input.addEventListener('input', () => { state.fills[k] = input.value; renderOut(); });
    el.blankGrid.append(h('label', { for: id }, h('span', { text: k.charAt(0) + k.slice(1).toLowerCase() }), input));
  });
}

/* word-level diff (longest common subsequence) */
function tokens(t) { return t.match(/\n|[^\s]+/g) || []; }
function norm(t) { return t === '\n' ? t : (t.toLowerCase().replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '') || t.toLowerCase()); }
function diffWords(a, b) {
  const A = tokens(a), B = tokens(b), n = A.length, m = B.length;
  if (n * m > 6e6) return null;
  const na = A.map(norm), nb = B.map(norm), w = m + 1;
  const dp = new Uint16Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i * w + j] = na[i] === nb[j] ? dp[(i + 1) * w + j + 1] + 1 : Math.max(dp[(i + 1) * w + j], dp[i * w + j + 1]);
  const ops = []; let i = 0, j = 0;
  while (i < n && j < m) {
    if (na[i] === nb[j]) { ops.push(['eq', B[j]]); i++; j++; }
    else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) { ops.push(['del', A[i]]); i++; }
    else { ops.push(['ins', B[j]]); j++; }
  }
  while (i < n) ops.push(['del', A[i++]]);
  while (j < m) ops.push(['ins', B[j++]]);
  return ops;
}
function renderRedline() {
  el.changes.replaceChildren(...state.result.changes.map(c => h('li', { text: c })));
  el.diff.replaceChildren();
  const ops = diffWords(state.prompt, current().text);
  el.diffNote.hidden = true;
  if (!ops) {
    el.diff.textContent = current().text;
    el.diffNote.textContent = 'This prompt is too long to mark up word by word, so the plain result is shown.';
    el.diffNote.hidden = false;
    return;
  }
  // merge consecutive tokens of the same kind so underlines and strikes run unbroken
  const frag = document.createDocumentFragment();
  let kind = null, buf = '';
  const flush = () => {
    if (!buf) return;
    const text = buf.replace(/ +$/, '');
    const trailing = buf.slice(text.length);
    frag.append(kind === 'ins' ? h('ins', { text }) : kind === 'del' ? h('del', { text }) : document.createTextNode(text), trailing);
    buf = '';
  };
  for (const [k, tok] of ops) {
    if (tok === '\n') {
      if (k === 'del') continue;            // a removed line break leaves no mark
      flush(); frag.append('\n'); kind = null; continue;
    }
    if (k !== kind) { flush(); kind = k; }
    buf += tok + ' ';
  }
  flush();
  el.diff.append(frag);
}

let countFrame;
function renderMargin(animate) {
  const r = state.result;
  el.rubric.replaceChildren();
  for (const d of DIMENSIONS) {
    const row = r ? r.rubric[d.key] : null;
    const seg = (n, cls) => h('div', { class: `bar ${cls}` }, [0, 1, 2].map(i => h('i', { class: i < n ? 'on' : null })));
    el.rubric.append(h('li', {},
      h('div', { class: 'r-top' }, h('span', { text: d.label }), h('span', { class: 'r-val', text: row ? `${row.before} to ${row.after} of 3` : '' })),
      row ? h('div', { class: 'bars', 'aria-hidden': 'true' }, seg(row.before, 'before'), seg(row.after, 'after'))
          : h('p', { class: 'r-hint', text: d.hint })));
  }
  el.gapsWrap.hidden = !r || r.gaps.length === 0;
  el.gaps.replaceChildren(...(r ? r.gaps : []).map(g => h('li', { text: g })));

  if (!r) { el.track.hidden = true; el.scoreLine.textContent = 'Scored after you sharpen a prompt.'; return; }
  const { before, after } = r.score;
  const num = h('b', { text: String(animate && !reducedMotion() ? before : after) });
  el.scoreLine.replaceChildren(
    h('span', { text: 'Score ' }), num, h('span', { text: ` out of 100, up from ${before}.` }));
  el.track.hidden = false;
  const tb = el.track.querySelector('.before'), ta = el.track.querySelector('.after');
  tb.style.width = before + '%'; ta.style.width = '0%';
  requestAnimationFrame(() => requestAnimationFrame(() => { ta.style.width = after + '%'; }));
  cancelAnimationFrame(countFrame);
  if (animate && !reducedMotion() && after !== before) {
    const t0 = performance.now(), dur = 700;
    const tick = now => {
      const p = Math.min(1, (now - t0) / dur);
      num.textContent = String(Math.round(before + (after - before) * (1 - Math.pow(1 - p, 3))));
      if (p < 1) countFrame = requestAnimationFrame(tick);
    };
    countFrame = requestAnimationFrame(tick);
  }
}

/* ------------------------------------------------------------------ tabs */
const TABS = ['prompt', 'redline', 'compare'];
function setTab(name) {
  for (const t of TABS) {
    const sel = t === name;
    $('tab-' + t).setAttribute('aria-selected', String(sel));
    $('tab-' + t).tabIndex = sel ? 0 : -1;
    $('panel-' + t).hidden = !sel;
  }
}
TABS.forEach((t, i) => {
  const tab = $('tab-' + t);
  tab.addEventListener('click', () => setTab(t));
  tab.addEventListener('keydown', e => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const next = TABS[(i + step + TABS.length) % TABS.length];
    setTab(next); $('tab-' + next).focus();
  });
});

REFINEMENTS.forEach(([key, label]) => {
  el.refine.append(h('button', { type: 'button', class: 'chip', text: label, onclick: () => refine(key, label) }));
});

/* ------------------------------------------------------------------ copy, download, share */
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch (_) {
    const ta = h('textarea', { 'aria-hidden': 'true' });
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.append(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) { /* ignore */ }
    ta.remove();
    return ok;
  }
}
$('copyBtn').addEventListener('click', async () => {
  const left = [...current().text.matchAll(PLACEHOLDER)].filter(m => !(state.fills[m[1]] || '').trim()).length;
  const ok = await copyText(applyFills(current().text));
  toast(!ok ? 'Copy failed. Select the text and copy it by hand.' : left ? `Copied. ${left} blank${left > 1 ? 's' : ''} still unfilled.` : 'Prompt copied');
});
$('downloadBtn').addEventListener('click', () => {
  const slug = (state.result.title || 'prompt').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'prompt';
  const url = URL.createObjectURL(new Blob([applyFills(current().text) + '\n'], { type: 'text/markdown;charset=utf-8' }));
  const a = h('a', { href: url, download: `${slug}.md` });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

const b64 = {
  enc(s) { let bin = ''; new TextEncoder().encode(s).forEach(c => (bin += String.fromCharCode(c))); return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); },
  dec(s) { const bin = atob(s.replace(/-/g, '+').replace(/_/g, '/')); return new TextDecoder().decode(Uint8Array.from(bin, c => c.charCodeAt(0))); },
};
$('shareBtn').addEventListener('click', async () => {
  const r = state.result;
  const payload = { p: state.prompt, m: state.mode, t: state.target, r: { ...r, sharpened: current().text } };
  const url = `${location.origin}${location.pathname}#s=${b64.enc(JSON.stringify(payload))}`;
  toast((await copyText(url)) ? 'Share link copied' : 'Copy failed');
});
function restoreFromHash() {
  const m = location.hash.match(/^#s=([\w-]+)$/);
  if (!m) return false;
  try {
    const p = JSON.parse(b64.dec(m[1]));
    const result = validateResult(p.r);
    if (!result || typeof p.p !== 'string' || !p.p.trim()) return false;
    state.prompt = p.p.slice(0, MAX_PROMPT);
    state.mode = MODES.includes(p.m) ? p.m : 'general';
    state.target = TARGETS.includes(p.t) ? p.t : 'any';
    state.fills = {};
    el.prompt.value = state.prompt; el.mode.value = state.mode; el.target.value = state.target;
    updateCount(); autosize();
    loadResult(result, [{ label: 'Shared', text: result.sharpened }]);
    return true;
  } catch (_) { return false; }
}

/* ------------------------------------------------------------------ history */
function readHistory() {
  try { const h = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); return Array.isArray(h) ? h : []; }
  catch (_) { return []; }
}
function writeHistory(list) { try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list)); } catch (_) { /* private mode */ } }
function pushHistory() {
  const r = state.result;
  const entry = { prompt: state.prompt, mode: state.mode, target: state.target, ts: Date.now(),
                  result: { ...r, sharpened: current().text } };
  const list = readHistory().filter(x => !(x.prompt === entry.prompt && x.mode === entry.mode && x.target === entry.target));
  writeHistory([entry, ...list].slice(0, HISTORY_MAX));
}
const dlg = $('recent');
function openRecent() {
  const list = readHistory(), ul = $('recentList');
  ul.replaceChildren();
  if (!list.length) ul.append(h('li', { class: 'recent-empty', text: 'Nothing here yet. Sharpen a prompt and it will appear.' }));
  list.forEach(entry => {
    const result = validateResult(entry.result);
    if (!result) return;
    ul.append(h('li', {}, h('button', { type: 'button', class: 'recent-item', onclick: () => {
      state.prompt = String(entry.prompt || '').slice(0, MAX_PROMPT);
      state.mode = MODES.includes(entry.mode) ? entry.mode : 'general';
      state.target = TARGETS.includes(entry.target) ? entry.target : 'any';
      state.fills = {};
      el.prompt.value = state.prompt; el.mode.value = state.mode; el.target.value = state.target;
      updateCount(); autosize(); clearError(); setTab('prompt');
      loadResult(result, [{ label: 'Saved', text: result.sharpened }]);
      dlg.close();
    } }, h('b', { text: result.title }), h('span', { text: entry.prompt }))));
  });
  dlg.showModal();
}
$('recentBtn').addEventListener('click', openRecent);
$('recentClose').addEventListener('click', () => dlg.close());
$('recentClear').addEventListener('click', () => { writeHistory([]); openRecent(); dlg.close(); toast('History cleared'); });
dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });

/* ------------------------------------------------------------------ theme */
function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }
try { applyTheme(localStorage.getItem(THEME_KEY)); } catch (_) { /* ignore */ }
$('themeBtn').addEventListener('click', () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  const next = dark ? 'light' : 'dark';
  applyTheme(next);
  try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* ignore */ }
});

/* ------------------------------------------------------------------ init */
(async function init() {
  updateCount(); autosize(); setTab('prompt'); renderMargin(false);
  if (!restoreFromHash()) el.result.hidden = true;
  try {
    const s = await (await fetch('/api/status')).json();
    $('demoBanner').hidden = !s.demo;
    if (s.configured && !s.demo && s.model) $('modelNote').textContent = ` Model: ${s.model} on ${s.provider}.`;
    if (!s.configured) showError('The server has no model API key yet. Set GROQ_API_KEY or XAI_API_KEY, or DEMO_MODE=1 to try the interface.');
  } catch (_) { /* status is optional */ }
})();
