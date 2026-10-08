'use strict';
/* T3 Desk UI. Plain JavaScript, no framework, no network except this server's own /api.
 * All visible text comes from labels (labels_ui_vi.yaml via /api/meta): use the T helper.
 * Four panes (docs/UI-V2-SPEC.md): 1 menu and decision tree, 2 list or breakdown chart, 3 table (grid.js),
 * 4 context, notes (notes.js) and the Hermes placeholder. Shortcuts are in keys.js. */

const SESSION = document.querySelector('meta[name="session"]').content;
const S = {
  meta: null, st: null, screen: 'khoi_tao', node: '', owner: '', treeName: '', treeData: null, fnode: '',
  names: {}, panel: 'open', renderId: 0, sort: {}, lastLeaf: '', tableCache: {},
  sel: null, tabs: {}, collapsed: {}, pendingSelect: null, arch: '',
};

/* which screen shows which table (for "go to this row" from the palette, the draft list and the tree) */
const TABLE_SCREEN = {
  yeu_cau: 'yeu_cau', kien_truc: 'kien_truc', nut: 'cay', phan_bo: 'phan_bo', thong_so: 'nut', ung_vien: 'nut',
  doi_chieu: 'nut', mua_hang: 'mua_hang', rfq: 'rfq', moc: 'moc', quyet_dinh: 'moc', sai_lech: 'ra_soat',
  cai_dat: 'khoi_tao', cong_viec: 'tong_quan', ghi_chu: 'tong_quan', hang_muc: 'thu_vien',
};
const NODE_TABS = ['nut', 'phan_bo', 'thong_so', 'ung_vien', 'doi_chieu', 'mua_hang'];
const SCREEN_TABS = { cay: NODE_TABS, phan_bo: NODE_TABS, nut: NODE_TABS, moc: ['moc', 'quyet_dinh'] };
const DEFAULT_TAB = { cay: 'nut', phan_bo: 'phan_bo', nut: 'thong_so', moc: 'moc' };
const NO_FOCUS_TAGS = ['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA', 'SUMMARY'];

/* ---------- text and helpers ---------- */

function T(key, vars) {
  const ui = (S.meta && S.meta.labels.ui) || {};
  let s = ui[key];
  if (s === undefined) return '[' + key + ']';
  for (const k in vars || {}) s = s.split('{' + k + '}').join(String(vars[k]));
  return s;
}

function fieldLabel(table, field) {
  const lab = S.meta.labels;
  const o = (lab.overrides || {})[table];
  return (o && o[field]) || (lab.fields || {})[field] || (lab.system_fields || {})[field] || field;
}
const tableLabel = (t) => S.meta.labels.tables[t] || t;
const specOf = (t) => S.meta.schema.tables[t];

/** Build an element. Anything with a click handler that is not already a control becomes keyboard-focusable
 *  (Tab, then Enter or Space), so every clickable thing can be used without a mouse. */
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const k in props || {}) {
    const v = props[k];
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'value') e.value = v;
    else if (v === true) e.setAttribute(k, '');
    else e.setAttribute(k, v);
  }
  if (props && props.onclick && !NO_FOCUS_TAGS.includes(tag.toUpperCase()) && !e.hasAttribute('tabindex')) {
    e.setAttribute('tabindex', '0');
    if (!e.hasAttribute('role')) e.setAttribute('role', 'button');
    e.addEventListener('keydown', (ev) => {
      if (ev.target === e && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); ev.stopPropagation(); e.click(); }
    });
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    e.appendChild(typeof kid === 'object' ? kid : document.createTextNode(String(kid)));
  }
  return e;
}

class ApiFail extends Error {
  constructor(err, status) { super((err && err.code) || 'internal'); this.err = err || {}; this.status = status || 0; }
}

async function api(path, opts) {
  const o = opts || {};
  let url = path;
  if (o.query) {
    const q = new URLSearchParams();
    for (const k in o.query) if (o.query[k] !== undefined && o.query[k] !== null) q.set(k, o.query[k]);
    url += '?' + q.toString();
  }
  let res;
  try {
    res = await fetch(url, {
      method: o.body !== undefined ? 'POST' : 'GET',
      headers: { 'X-T3-Session': SESSION, 'Content-Type': 'application/json' },
      body: o.body !== undefined ? JSON.stringify(o.body) : undefined,
    });
  } catch (e) {
    throw new ApiFail({ code: 'net', detail: String(e) }, 0);
  }
  let data;
  try { data = await res.json(); } catch (e) { data = { error: { code: 'internal', detail: String(res.status) } }; }
  if (!res.ok) throw new ApiFail(data.error, res.status);
  if (data && data.names) S.names = Object.assign({}, S.names, data.names); // code -> name, shown beside every code
  return data;
}

let toastTimer = null;
function toast(text, detail, isError) {
  const box = document.getElementById('toast');
  box.textContent = '';
  box.appendChild(h('div', { text }));
  if (detail) box.appendChild(h('div', { class: 'detail', text: detail }));
  box.className = isError ? 'error' : '';
  box.hidden = false;
  clearTimeout(toastTimer);
  if (!isError) toastTimer = setTimeout(() => { box.hidden = true; }, detail ? 7000 : 4000);
}
document.getElementById('toast').addEventListener('click', () => { document.getElementById('toast').hidden = true; });

function showError(e) {
  const err = e instanceof ApiFail ? e.err : { code: 'internal', detail: String(e) };
  const known = S.meta && (S.meta.labels.ui['err_' + err.code] !== undefined);
  toast(known ? T('err_' + err.code) : T('err_internal'), err.detail, true);
}

async function guard(fn) {
  try { return await fn(); } catch (e) { showError(e); return undefined; }
}

const num = (v) => (v === null || v === undefined || v === '' ? '' : v);
function fmtAge(sec) {
  if (sec === null || sec === undefined) return T('age_never');
  if (sec < 90) return T('age_seconds', { n: Math.round(sec) });
  if (sec < 5400) return T('age_minutes', { n: Math.round(sec / 60) });
  return T('age_hours', { n: Math.round(sec / 3600) });
}

/* ---------- dialogs: only the few that are not "add or edit a record" ---------- */

function closeModal() {
  document.getElementById('modal-root').textContent = '';
}

function modal(title, bodyEl, buttons) {
  const root = document.getElementById('modal-root');
  root.textContent = '';
  const dlg = h('div', { class: 'dialog', role: 'dialog', 'aria-modal': 'true' },
    h('header', { text: title }), h('div', { class: 'body' }, bodyEl), h('footer', null, buttons));
  root.appendChild(h('div', { class: 'overlay' }, dlg));
  const first = dlg.querySelector('input:not([readonly]), select, textarea, button.primary');
  if (first) first.focus();
  return dlg;
}

/* ---------- shell: top bar, menu, status bar ---------- */

function buildNav() {
  const nav = document.getElementById('nav');
  nav.textContent = '';
  for (const key of S.meta.screens) {
    const b = h('button', { type: 'button', 'data-screen': key, onclick: () => go(key) },
      h('span', { text: T('nav_' + key) }), h('span', { class: 'badge', 'data-count': key, hidden: true }));
    nav.appendChild(b);
  }
}

function markNav() {
  const counts = (S.st && S.st.menu_counts) || {};
  for (const b of document.querySelectorAll('#nav button')) {
    const key = b.dataset.screen;
    if (key === S.screen) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    const badge = b.querySelector('.badge');
    const c = counts[key];
    if (!badge) continue;
    badge.hidden = !c || !c.n;
    badge.textContent = c ? String(c.n) : '';
    badge.classList.toggle('red', !!(c && c.red));
    badge.classList.toggle('draft', key === 'commit' && !!(c && c.n));
  }
}

function renderStatus() {
  const st = S.st;
  const top = document.getElementById('top-info');
  const bar = document.getElementById('status');
  top.textContent = '';
  bar.textContent = '';
  if (!st) return;
  const conn = st.connection;
  const roleName = st.role ? T('role_' + st.role) : T('none');
  const connText = T('conn_' + conn.state) + (conn.state === 'offline' && st.cache_age_seconds !== null
    ? ' - ' + T('cache_age', { age: fmtAge(st.cache_age_seconds) }) : '');
  top.appendChild(h('span', { id: 'st-project', text: T('st_project') + ': ' + (st.project || T('none')) }));
  top.appendChild(h('span', { id: 'st-user', text: T('st_user') + ': ' + (st.user || T('none')) + ' (' + roleName + ')' }));
  top.appendChild(h('span', { class: 'sp' }));
  top.appendChild(h('span', { id: 'st-conn', class: 'state-' + conn.state, text: T('st_teable') + ': ' + connText, title: conn.message || '' }));
  top.appendChild(h('span', { id: 'st-drafts', text: T('st_drafts') + ': ' + st.drafts }));
  top.appendChild(h('button', { class: 'btn primary', type: 'button', id: 'btn-top-commit', text: T('btn_commit_top', { mod: S.meta.modifier }),
    disabled: !st.can_commit || !st.drafts, title: st.can_commit ? '' : T('commit_disabled'), onclick: () => commitNow() }));
  bar.appendChild(h('span', { text: T('st_legend') }));
  bar.appendChild(h('span', { id: 'st-cache', text: T('cache_age', { age: fmtAge(st.cache_age_seconds) }) }));
  bar.appendChild(h('span', { id: 'st-invalid', class: st.invalid_drafts ? 'err' : 'muted', text: T('st_drafts_state', { n: st.drafts, bad: st.invalid_drafts || 0 }) }));
  if (st.progress && st.progress.table) {
    bar.appendChild(h('span', { id: 'st-progress', text: T('st_loading', { table: tableLabel(st.progress.table), n: st.progress.count }) }));
  }
  bar.appendChild(h('span', { class: 'muted', text: T('st_keys', { mod: S.meta.modifier }) }));
  markNav();
}

async function loadState() {
  try { S.st = await api('/api/state'); } catch (e) { showError(e); }
  renderStatus();
  return S.st;
}

/* ---------- pane 1: the decision tree as a checklist ---------- */

function setPanel(mode) {
  S.panel = mode === 'strip' ? 'strip' : 'open';
  document.getElementById('shell').dataset.panel = S.panel;
  document.getElementById('panel-toggle').textContent = S.panel === 'strip' ? '»' : '«';
  document.getElementById('panel-toggle').title = S.panel === 'strip' ? T('panel_open') : T('panel_collapse');
  try { localStorage.setItem('t3_panel', S.panel); } catch (e) { /* storage may be blocked: the pane still works */ }
}

async function loadTrees() {
  let data;
  try { data = await api('/api/trees', { query: { node: S.node } }); } catch (e) { showError(e); return; }
  S.treeData = data;
  if (!S.treeName || !data.trees[S.treeName]) S.treeName = data.first;
  drawTreePane();
}

function drawTreePane() {
  const data = S.treeData;
  if (!data) return;
  const info = document.getElementById('panel-node');
  info.textContent = '';
  info.appendChild(document.createTextNode(S.node ? T('panel_node', { node: withName('nut', S.node) }) : T('panel_no_node')));
  if (S.node) info.appendChild(h('button', { class: 'btn small', type: 'button', text: T('panel_clear_node'), onclick: () => selectNode('') }));
  const tabs = document.getElementById('tree-tabs');
  tabs.textContent = '';
  for (const name of S.meta.tree_names) {
    tabs.appendChild(h('button', { type: 'button', role: 'tab', 'data-tree': name, 'aria-selected': String(name === S.treeName),
      text: T('tree_' + name), onclick: () => { S.treeName = name; drawTreePane(); } }));
  }
  const tree = data.trees[S.treeName];
  if (!tree) return;
  drawChecklist(tree, data.guide || []);
}

/** "Which step are you at?": steps done are ticked, the step you are at is highlighted with its guidance. */
function drawChecklist(tree, guide) {
  const box = document.getElementById('tree-list');
  box.textContent = '';
  const list = h('ol', { class: 'check-list', id: 'check-list' });
  for (const q of tree.questions) {
    const step = (tree.steps || []).find((s) => s.index === q.index);
    const here = !!tree.leaf && tree.leaf.index === q.index;
    const state = !tree.highlighted ? 'ref' : (here ? 'here' : (step && !step.ends_here ? 'done' : 'todo'));
    const li = h('li', { class: 'q ' + state, 'data-q': q.index });
    li.appendChild(h('span', { class: 'mark', text: state === 'done' ? '✓ ' : (state === 'here' ? '▶ ' : '') }));
    li.appendChild(document.createTextNode(q.q));
    if (here) {
      const leaf = tree.leaf;
      li.appendChild(h('div', { class: 'here-do' }, h('b', { text: T('here_label') + ': ' }), leaf.do,
        leaf.screen ? h('button', { class: 'btn small', type: 'button', text: T('btn_open'), onclick: () => go(leaf.screen, { node: S.node }) }) : null));
      if (q.help) li.appendChild(h('div', { class: 'here-help' }, h('b', { text: T('guide_here') + ': ' }), q.help));
    }
    list.appendChild(li);
  }
  box.appendChild(list);
  const help = document.getElementById('tree-help');
  help.textContent = '';
  const steps = tree.questions.filter((q) => q.help);
  if (steps.length) help.appendChild(h('details', null, h('summary', { text: T('guide_all') }), steps.map((q) => h('p', null, h('b', { text: q.q + ' ' }), q.help))));
  if (guide.length) help.appendChild(h('details', { id: 'guide-glossary' }, h('summary', { text: T('guide_glossary') }), guide.map((g) => h('p', null, h('b', { text: g.term + ': ' }), g.text))));
  const here = list.querySelector('.q.here');
  const sig = S.treeName + ':' + (tree.leaf ? tree.leaf.index + ':' + tree.leaf.answer : '');
  if (here && sig !== S.lastLeaf) { S.lastLeaf = sig; here.scrollIntoView({ block: 'nearest' }); }
}

/** F1: the same tree as a diagram, larger, in front of the working panes. */
function widenPanel() {
  const data = S.treeData;
  if (!data || !data.trees[S.treeName]) return;
  const holder = h('div', { id: 'tree-view', class: 'tree-wide' });
  modal(T('panel_title') + ' - ' + T('tree_' + S.treeName), [holder], [h('button', { class: 'btn primary', type: 'button', text: T('btn_close'), onclick: closeModal })]);
  TreeView.draw(holder, data.trees[S.treeName], {
    yesText: T('answer_yes'), noText: T('answer_no'),
    onAction: (screen) => { closeModal(); go(screen, { node: S.node }); }, onLeaf: (el) => el.scrollIntoView({ block: 'center' }),
  });
}

async function selectNode(code) {
  S.node = code;
  await loadTrees();
  if (S.screen === 'nut' || S.screen === 'cay' || S.screen === 'phan_bo') render();
}

/* ---------- navigation and the four-pane workspace ---------- */

const Workspace = {
  current: null, grid: null,
  /** Ctrl+PageUp / PageDown: the next or previous tab of pane 3. */
  tab(dir) {
    const ws = this.current;
    if (!ws || !ws.tabs) return;
    const items = ws.tabs.items;
    const at = items.findIndex((t) => t.key === ws.tabs.active);
    const next = items[(at + dir + items.length) % items.length];
    if (next) ws.tabs.pick(next.key);
  },
};
const Chart = { current: null };

function go(screen, opts) {
  const o = opts || {};
  S.screen = screen;
  S.fnode = o.node || '';
  if (o.node) S.node = o.node;
  S.owner = o.owner || '';
  if (o.tab) S.tabs[screen] = o.tab;
  S.sel = null;
  render();
  loadTrees();
}

/** Open the screen that shows a row and put the cursor on it (palette, draft list, notes). */
async function jumpTo(table, key) {
  const data = await getRows(table);
  const row = data.rows.find((r) => r.key === key);
  if (table === 'ghi_chu' && row) return jumpTo(row.fields.bang, row.fields.ma_ban_ghi); // a note: go to what it is about
  S.pendingSelect = { table, key };
  const screen = TABLE_SCREEN[table] || 'tong_quan';
  go(screen, { node: row ? row.node : '', tab: SCREEN_TABS[screen] && SCREEN_TABS[screen].includes(table) ? table : undefined });
}

function setPane(idTitle, idBody, title, body) {
  document.getElementById(idTitle).textContent = title || '';
  const holder = document.getElementById(idBody);
  holder.textContent = '';
  if (body) holder.appendChild(body);
}

async function render() {
  const id = ++S.renderId;
  markNav();
  const before = Workspace.grid && S.screen === S.lastScreen ? Workspace.grid.cursorState() : null;
  const scroll3 = document.getElementById('p3-body').scrollTop;
  const ws = { p2: h('div', { class: 'p2-inner' }), p3: h('div', { class: 'p3-inner' }), t2: '', t3: '', tabs: null, bar: null, grid: null };
  try {
    await (SCREENS[S.screen] || SCREENS.khoi_tao)(ws);
  } catch (e) {
    ws.p3 = h('p', { class: 'err pad', text: T('err_screen') });
    showError(e);
  }
  if (id !== S.renderId) return;
  setPane('p2-title', 'p2-body', ws.t2, ws.p2);
  setPane('p3-title', 'p3-body', ws.t3, ws.p3);
  const tabs = document.getElementById('p3-tabs');
  tabs.textContent = '';
  if (ws.tabs) {
    for (const t of ws.tabs.items) {
      tabs.appendChild(h('button', { type: 'button', role: 'tab', 'data-tab': t.key, 'aria-selected': String(t.key === ws.tabs.active),
        text: tableLabel(t.key) + (t.count !== undefined ? ' (' + t.count + ')' : ''), onclick: () => ws.tabs.pick(t.key) }));
    }
  }
  tabs.hidden = !ws.tabs;
  const bar = document.getElementById('p3-bar');
  bar.textContent = '';
  if (ws.bar) bar.appendChild(ws.bar);
  bar.hidden = !ws.bar;
  Workspace.current = ws;
  Workspace.grid = ws.grid;
  if (ws.grid) Grid.current = ws.grid;
  if (before && ws.grid && !S.pendingSelect) ws.grid.restoreCursor(before);
  const sameScreen = S.lastScreen === S.screen;
  document.getElementById('p3-body').scrollTop = sameScreen ? scroll3 : 0; // a new screen starts at the top
  if (!sameScreen) document.getElementById('p2-body').scrollTop = 0;
  S.lastScreen = S.screen;
  drawContext();
  if (S.pendingSelect && ws.grid && ws.grid.table === S.pendingSelect.table) {
    ws.grid.focusKey(S.pendingSelect.key);
    ws.grid.focus();
  }
  S.pendingSelect = null;
  if (S.afterRender) { const f = S.afterRender; S.afterRender = null; f(); }
}

async function refreshAll() {
  await loadState();
  await render();
  await loadTrees();
}

/** The user reached for a different row: pane 4 follows (a short pause keeps arrow-key runs cheap). */
let selTimer = null;
function select(table, key) {
  const same = (S.sel && S.sel.table === table && S.sel.key === key) || (!S.sel && !key);
  if (same) return;
  S.sel = key ? { table, key } : null;
  for (const el of document.querySelectorAll('#p2-body [data-key]')) el.classList.toggle('sel', !!key && el.dataset.key === key);
  clearTimeout(selTimer);
  selTimer = setTimeout(drawContext, 90);
}

/* ---------- pane 4: context, notes, Hermes ---------- */

function drawHermes(body, ctxKey) {
  const box = h('div', { class: 'hermes', id: 'hermes-box' });
  body.appendChild(box);
  api('/api/assistant', { query: { context: ctxKey || '' } }).then((data) => {
    box.appendChild(h('h3', { class: 'pane-sub' }, T('hermes_title'), ' ', h('span', { class: 'badge', id: 'hermes-state', text: data.enabled ? T('hermes_on') : T('hermes_off') })));
    box.appendChild(h('p', { class: 'muted', text: T('hermes_note') }));
    const actions = data.enabled ? data.actions : [{ id: 'find', label: T('hermes_find') }, { id: 'suggest', label: T('hermes_suggest') }, { id: 'context', label: T('hermes_context') }];
    box.appendChild(h('div', { class: 'hermes-actions' }, actions.map((a) => h('button', { class: 'btn small', type: 'button', 'data-hermes': a.id,
      disabled: !data.enabled, text: a.label }))));
    box.appendChild(h('input', { id: 'hermes-ask', type: 'text', disabled: !data.enabled, placeholder: T('hermes_ask_off'), 'aria-label': T('hermes_ask_off') }));
  }).catch(() => { /* the placeholder is optional: no endpoint, no panel */ });
}

function ctxBlock(table, b) {
  const title = b.title_key ? h('h4', { text: T(b.title_key) }) : null;
  if (b.type === 'kv') {
    return h('div', { class: 'ctx ctx-kv' }, title, h('dl', null, b.items.map((it) => [
      h('dt', { text: it.field ? fieldLabel(table, it.field) : T(it.label_key) }), h('dd', { text: String(it.value) })])));
  }
  if (b.type === 'chips' || b.type === 'warnings') {
    const items = b.type === 'warnings' ? b.items.map((t) => ({ text: t, bad: true })) : b.items;
    return h('div', { class: 'ctx' }, title, items.length
      ? h('div', null, items.map((c) => h('span', { class: 'chip' + (c.bad ? ' bad' : ''), text: c.text })))
      : h('span', { class: 'muted', text: T('ov_none') }));
  }
  if (b.type === 'text') return h('div', { class: 'ctx' }, title, h('p', { text: b.text || T('ov_none') }));
  if (b.type === 'help') {
    const known = S.meta.labels.ui[b.label_key] !== undefined && S.meta.labels.ui[b.label_key] !== '';
    return h('div', { class: 'help' }, h('b', { text: T('help_title') + ': ' }), T(known ? b.label_key : 'help_generic'));
  }
  return null;
}

async function drawContext() {
  const body = document.getElementById('p4-body');
  const sel = S.sel;
  const title = document.getElementById('p4-title');
  if (!sel) {
    title.textContent = T('p4_title');
    body.textContent = '';
    body.appendChild(h('p', { class: 'muted pad', text: T('p4_none') }));
    drawHermes(body, '');
    return;
  }
  let ctx;
  try {
    ctx = await api('/api/context', { query: { table: sel.table, key: sel.key } });
  } catch (e) {
    if (S.sel === sel) { body.textContent = ''; body.appendChild(h('p', { class: 'muted pad', text: T('p4_none') })); }
    return;
  }
  if (S.sel !== sel) return; // the user moved on while this was loading
  title.textContent = T('p4_row', { title: ctx.title });
  const scroll = body.scrollTop;
  body.textContent = '';
  const info = h('div', { class: 'ctx-wrap', id: 'ctx-blocks' }, ctx.blocks.map((b) => ctxBlock(sel.table, b)));
  body.appendChild(info);
  const notes = h('div', { class: 'notes', id: 'notes-box' });
  body.appendChild(notes);
  await guard(() => drawNotes(notes, sel.table, sel.key));
  drawHermes(body, sel.table + '.row');
  body.scrollTop = scroll;
}

window.onNotesChanged = () => { if (Workspace.grid) Workspace.grid.reload(); };

/* ---------- shared helpers ---------- */

async function getRows(table, filter) {
  const q = { table };
  if (filter && filter.node) q.node = filter.node;
  if (filter && filter.owner) q.owner = filter.owner;
  return api('/api/rows', { query: q });
}

async function idChoices(ref) {
  if (!S.tableCache[ref]) {
    const data = await getRows(ref);
    S.tableCache[ref] = data.rows.map((r) => r.key);
  }
  return S.tableCache[ref];
}

function settingLabel(key) {
  return ((S.meta.labels.settings_keys || {})[key]) || '';
}

/* "N1 - Propulsion": a code is never shown alone when its name is known */
function withName(ref, code) {
  const nm = ((S.names || {})[ref] || {})[code];
  return nm ? code + ' - ' + nm : code;
}

function sortRows(table, rows) {
  const s = S.sort[table];
  if (!s) return rows;
  const get = (r) => (s.extra ? (r.extras || {})[s.col] : r.fields[s.col]);
  const out = rows.slice();
  out.sort((a, b) => {
    const x = get(a), y = get(b);
    const nx = typeof x === 'number', ny = typeof y === 'number';
    let c;
    if (nx && ny) c = x - y; else c = String(x === undefined || x === null ? '' : x).localeCompare(String(y === undefined || y === null ? '' : y), undefined, { numeric: true });
    return s.dir * c;
  });
  return out;
}

async function exportCsv(table) {
  await guard(async () => {
    const q = { table };
    if (S.node && NODE_TABS.includes(table)) q.node = S.node;
    const res = await api('/api/csv', { query: q });
    const blob = new Blob([res.text], { type: 'text/csv;charset=utf-8' });
    const a = h('a', { href: URL.createObjectURL(blob), download: res.filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(T('csv_done', { name: res.filename }));
  });
}

/** A short title for a row in the pane 2 list: "code - name" whenever a name is known. */
function rowTitle(table, row) {
  const known = ((S.names || {})[table] || {})[row.key];
  if (known) return row.key + ' - ' + known;
  const spec = specOf(table);
  for (const [name, fs] of Object.entries(spec.fields)) {
    if (name === spec.id_field || fs.type === 'choice' || fs.type === 'number' || fs.type === 'date') continue;
    const v = row.fields[name];
    if (v) return row.key + ' - ' + String(v).slice(0, 40);
  }
  return row.key;
}

/** Pane 2 as a list with a filter box. `onPick(key)` puts the cursor of the table on that row. */
function rowList(table, rows, onPick, o) {
  const opts = o || {};
  const input = h('input', { type: 'search', class: 'list-filter', id: 'p2-filter', 'aria-label': T('filter_text'), placeholder: T('filter_text') });
  const ul = h('ul', { class: 'plain list-pane', id: 'row-list' });
  const draw = (all) => {
    const q = input.value.trim().toLowerCase();
    ul.textContent = '';
    for (const row of all) {
      const title = rowTitle(table, row);
      if (q && !title.toLowerCase().includes(q)) continue;
      const dot = opts.dot ? opts.dot(row) : (row.warnings && row.warnings.length ? 'r' : (row.draft ? 'y' : ''));
      ul.appendChild(h('li', { class: 'item' + (S.sel && S.sel.key === row.key ? ' sel' : ''), 'data-key': row.key, onclick: () => onPick(row.key) },
        h('span', { class: 'dot ' + dot }), h('span', { class: 'nm', text: title }),
        row.draft ? h('span', { class: 'mark', text: '✎' }) : null,
        row.warnings && row.warnings.length ? h('span', { class: 'badge warn', title: row.warnings.join('\n'), text: '! ' + row.warnings.length }) : null,
        row.notes ? h('span', { class: 'badge note', title: T('notes_title', { key: withName(table, row.key) }), text: '✉ ' + row.notes }) : null,
        opts.side ? h('span', { class: 'nx', text: opts.side(row) }) : null));
    }
    if (!ul.firstChild) ul.appendChild(h('li', { class: 'muted pad', text: T('empty') }));
  };
  input.addEventListener('input', () => draw(rowList.last || rows));
  draw(rows);
  const el = h('div', { class: 'list-wrap' }, input, ul);
  return { el, update: (all) => { rowList.last = all; draw(all); } };
}

/** One grid in pane 3 with its toolbar. Returns the grid; the workspace holds on to it for the keyboard. */
async function gridFor(ws, table, o) {
  const opts = o || {};
  const filter = { node: opts.node || '', owner: opts.owner || '' };
  const fetch = () => getRows(table, filter);
  const data = await fetch();
  const grid = buildGrid(table, data, {
    fetch, prefill: opts.prefill, actions: opts.actions, noNew: opts.noNew,
    onSelect: (row) => select(row ? table : null, row ? row.key : null),
    onChange: () => { if (opts.onChange) opts.onChange(grid); },
  });
  ws.grid = grid;
  const bar = h('div', { class: 'toolbar' },
    h('button', { class: 'btn primary', type: 'button', id: 'btn-new-' + table, text: T('btn_new_row'), onclick: () => grid.newRow() }),
    h('span', { class: 'muted grow', text: T('grid_hint', { mod: S.meta.modifier }) }),
    opts.barExtra || null,
    h('button', { class: 'btn small', type: 'button', text: T('btn_csv'), onclick: () => exportCsv(table) }));
  grid.bar = bar;
  if (!opts.inline) ws.bar = bar;
  return grid;
}

/** Pane 2 list and pane 3 grid of one table (requirements, architectures, RFQ, milestones...). */
async function listAndGrid(ws, table, o) {
  const opts = o || {};
  ws.t2 = T('p2_list', { table: tableLabel(table) });
  ws.t3 = tableLabel(table);
  const holder = {};
  const grid = await gridFor(ws, table, Object.assign({}, opts, {
    onChange: (g) => { holder.list.update(g.rows); },
  }));
  holder.list = rowList(table, grid.rows, (key) => { grid.focusKey(key); grid.focus(); }, { side: opts.side, dot: opts.dot });
  ws.p2.appendChild(holder.list.el);
  ws.p3.appendChild(grid.el);
  const origReload = grid.reload;
  grid.reload = async () => { await origReload(); holder.list.update(grid.rows); };
  return grid;
}

/* ---------- pane 2 for the breakdown screens: the system chart and the library ---------- */

const CAP_KEYS = ['cap_0', 'cap_1', 'cap_2'];
const capLabel = (level) => T(CAP_KEYS[Math.max(0, Math.min(level, 2))]);
const DROP_MIME = 'text/plain';

/** Where a click or Enter in the library adds: under the selected node, or beside it when that is the last level. */
function addTarget() {
  const n = S.node && Chart.byCode ? Chart.byCode.get(S.node) : null;
  if (!n) return { parent: '', level: 0 };
  if (n.level >= 2) return { parent: n.parent, level: 1 };
  return { parent: n.code, level: n.level + 1 };
}

/** Put a library item (or a new placeholder) into the breakdown. Nothing is copied: the node points at the item. */
async function addToBreakdown(body, parent, after) {
  const target = parent === undefined ? addTarget() : { parent, level: ((Chart.byCode && Chart.byCode.get(parent)) || { level: -1 }).level + 1 };
  const send = Object.assign({ parent: target.parent }, body);
  const base = target.parent ? Chart.byCode && Chart.byCode.get(target.parent) : null;
  if (S.arch && (!target.parent || (base && base.level === 0)) && !send.ma_kt) send.ma_kt = S.arch;
  await guard(async () => {
    const res = await api('/api/breakdown/add', { body: send });
    if (res.node) S.node = res.node;
    if (res.node && target.parent) S.collapsed[target.parent] = false;
    toast(T(res.created_item ? (res.node ? 'lib_created_placed' : 'lib_created') : 'lib_added', { node: res.node || '', item: res.item }));
    if (after) go(after, { node: res.node }); else await refreshAll();
  });
}

function itemChips(it) {
  const cls = it.status === S.meta.values.lib_placeholder ? ' ph' : '';
  return [
    h('span', { class: 'cap', text: it.cap }),
    h('span', { class: 'chip item' + cls, text: it.status }),
    it.owner ? h('span', { class: 'own', text: it.owner }) : null,
    it.used ? h('span', { class: 'nx', title: it.places.join(', '), text: T('lib_used_n', { n: it.used }) }) : null,
  ];
}

/** The library under the chart: search what exists first, then add it to the selected node (button, Enter or drag). */
function libraryPanel(ws) {
  const box = h('div', { class: 'p2-library', id: 'lib-panel' });
  const search = h('input', { type: 'search', id: 'lib-search', class: 'list-filter', placeholder: T('lib_search'), 'aria-label': T('lib_search') });
  const mine = h('input', { type: 'checkbox', id: 'lib-mine' });
  const list = h('ul', { class: 'plain list-pane', id: 'lib-list' });
  const count = h('span', { class: 'badge', id: 'lib-count', text: '0' });
  const name = h('input', { type: 'text', id: 'lib-new', placeholder: T('lib_new_name'), 'aria-label': T('lib_new_name'), autocomplete: 'off' });
  const who = h('input', { type: 'text', id: 'lib-who', placeholder: T('lib_who'), 'aria-label': T('lib_who'), list: 'lib-people', autocomplete: 'off' });
  const people = h('datalist', { id: 'lib-people' });
  const create = async (place) => {
    const ten = name.value.trim();
    if (!ten) { name.focus(); return; }
    name.value = '';
    await addToBreakdown({ new: { ten, nguoi_dien: who.value.trim() || undefined }, place }, place === false ? '' : undefined);
  };
  name.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); create(ev.shiftKey ? false : true); }
  });
  let timer = null;
  const load = async () => {
    const d = await api('/api/library', { query: { q: search.value.trim(), mine: mine.checked ? '1' : '' } });
    count.textContent = String(d.items.length);
    people.textContent = '';
    d.people.forEach((p) => people.appendChild(h('option', { value: p })));
    list.textContent = '';
    for (const it of d.items) {
      const li = h('li', { class: 'item lib-item', 'data-key': it.key, draggable: 'true', tabindex: '0', title: T('lib_drag_hint'),
        onclick: () => select('hang_muc', it.key) },
        h('div', { class: 'r1' }, h('b', { class: 'code', text: it.key }), h('span', { class: 'nm', text: it.name }),
          h('button', { class: 'btn small', type: 'button', 'data-add': it.key, text: T('btn_add_plus'), title: T('lib_add_title'),
            onclick: (ev) => { ev.stopPropagation(); addToBreakdown({ item: it.key }); } })),
        h('div', { class: 'r2' }, itemChips(it)));
      li.addEventListener('dragstart', (ev) => { ev.dataTransfer.setData(DROP_MIME, 'hm:' + it.key); ev.dataTransfer.effectAllowed = 'copy'; });
      li.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && ev.target === li) { ev.preventDefault(); ev.stopPropagation(); addToBreakdown({ item: it.key }); }
      });
      list.appendChild(li);
    }
    if (!d.items.length) list.appendChild(h('li', { class: 'muted pad', text: T('lib_none') }));
  };
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => guard(load), 150); });
  mine.addEventListener('change', () => guard(load));
  box.appendChild(h('div', { class: 'lib-head' }, h('h3', { class: 'pane-sub' }, T('lib_title'), ' ', count),
    h('label', { class: 'switch' }, mine, T('lib_mine'))));
  box.appendChild(search);
  box.appendChild(h('div', { class: 'lib-new' }, name, who, people,
    h('button', { class: 'btn small primary', type: 'button', id: 'btn-lib-create', text: T('btn_create_add'), title: T('lib_create_title'), onclick: () => create(true) })));
  box.appendChild(list);
  ws.p2.appendChild(box);
  return load();
}

async function chartPane(ws) {
  const data = await api('/api/tree_nodes');
  ws.t2 = T('p2_chart');
  const byCode = new Map(data.nodes.map((n) => [n.code, n]));
  const children = new Map();
  for (const n of data.nodes) if (n.parent && byCode.has(n.parent)) children.set(n.parent, (children.get(n.parent) || []).concat(n));
  Chart.byCode = byCode;
  if (S.arch && !data.archs.some((x) => x.key === S.arch)) S.arch = '';

  const bar = h('div', { class: 'toolbar chart-bar' });
  for (const key of Object.keys(data.gates)) {
    const cb = h('input', { type: 'checkbox', id: 'gate-' + key, 'data-gate': key, disabled: !data.can_gate, checked: data.gates[key] || false,
      title: data.can_gate ? '' : T('role_needed') });
    cb.addEventListener('change', () => setGate(key, cb.checked, cb));
    bar.appendChild(h('label', { class: 'switch' }, cb, T('gate_' + key)));
  }
  const arch = h('select', { id: 'arch-filter', 'aria-label': T('arch_filter') }, h('option', { value: '', text: T('arch_all') }),
    data.archs.map((x) => h('option', { value: x.key, selected: x.key === S.arch, text: x.key + ' - ' + x.name + ' (' + x.status + ')' })));
  arch.addEventListener('change', () => { S.arch = arch.value; draw(); });
  bar.appendChild(h('label', { class: 'switch' }, T('arch_filter') + ': ', arch));
  bar.appendChild(h('button', { class: 'btn small', type: 'button', id: 'btn-add-child', text: T('btn_add_child_node'), onclick: () => Chart.current && Chart.current.addChild() }));
  const wrap = h('div', { id: 'chart', role: 'tree', 'aria-label': T('p2_chart') });
  const top = h('div', { class: 'p2-chart' }, bar, wrap);
  ws.p2.appendChild(top);

  const dropOn = (el, parent, ma_kt, allowed) => {
    el.addEventListener('dragover', (ev) => {
      if (!allowed) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'copy';
      el.classList.add('drop');
    });
    el.addEventListener('dragleave', () => el.classList.remove('drop'));
    el.addEventListener('drop', (ev) => {
      el.classList.remove('drop');
      const text = ev.dataTransfer.getData(DROP_MIME) || '';
      if (!allowed || !text.startsWith('hm:')) return;
      ev.preventDefault();
      addToBreakdown(Object.assign({ item: text.slice(3) }, ma_kt ? { ma_kt } : {}), parent);
    });
  };

  const nodeRow = (n, depth) => {
    const collapsed = !!S.collapsed[n.code];
    const hasKids = (children.get(n.code) || []).length > 0;
    const sel = n.code === S.node;
    const placeholder = n.item && n.item_status === S.meta.values.lib_placeholder;
    const row = h('div', { class: 'row' + (sel ? ' sel' : '') + (n.active === false ? ' inactive' : '') + (n.draft ? ' is-draft' : ''), role: 'treeitem',
      'data-code': n.code, 'data-level': String(n.level), 'data-depth': String(depth), 'aria-selected': String(sel),
      'aria-expanded': hasKids ? String(!collapsed) : undefined, tabindex: sel ? '0' : '-1', 'data-focus-first': sel,
      style: 'padding-left:' + (8 + depth * 16) + 'px', onclick: () => selectNode(n.code) },
      h('div', { class: 'r1' },
        h('span', { class: 'tw', text: hasKids ? (collapsed ? '▸' : '▾') : '' }),
        n.leaf ? h('span', { class: 'dot ' + (n.dot || ''), title: n.next }) : h('span', { class: 'dot' }),
        h('span', { class: 'cap cap-' + n.level, text: capLabel(n.level) }),
        h('b', { class: 'code', text: n.code }), h('span', { class: 'nm', text: n.name || T('node_unnamed') }),
        n.draft ? h('span', { class: 'mark', text: '✎' }) : null,
        n.warnings.length ? h('span', { class: 'badge warn', title: n.warnings.join('\n'), text: '! ' + n.warnings.length }) : null),
      h('div', { class: 'r2' },
        n.item ? h('span', { class: 'chip item' + (placeholder ? ' ph' : ''), title: n.item_status, text: n.item + (placeholder ? ' · ' + T('lib_placeholder_short') : '') }) : null,
        n.arch ? h('span', { class: 'chip arch', text: n.arch }) : null,
        n.owner ? h('span', { class: 'own', text: n.owner }) : null,
        h('span', { class: 'nx', text: n.next + (n.cost ? ' · ' + n.cost : ''), title: T('chart_cost', { n: n.cost }) })));
    dropOn(row, n.code, '', n.level < 2);
    return row;
  };

  const archHead = (a, depth, count) => {
    const head = h('div', { class: 'arch-head' + (a.key === S.arch ? ' sel' : ''), 'data-arch': a.key, style: 'padding-left:' + (8 + depth * 16) + 'px' },
      h('b', { text: a.key + ' - ' + a.name }), h('span', { class: 'chip arch', text: a.status }), h('span', { class: 'nx', text: T('arch_children', { n: count }) }),
      a.scaffold ? h('button', { class: 'btn small', type: 'button', 'data-scaffold': a.key, text: T('btn_scaffold'), title: T('scaffold_title'),
        onclick: (ev) => { ev.stopPropagation(); scaffoldArchitecture(a.key); } }) : null);
    const root = data.nodes.find((x) => !x.parent);
    dropOn(head, root ? root.code : '', a.key, true);
    return head;
  };

  const common = h('div', { class: 'arch-head common', style: '' }, h('b', { text: T('arch_common') }));

  const draw = () => {
    wrap.textContent = '';
    const visit = (n, depth) => {
      if (S.arch && n.arch && n.arch !== S.arch) return;
      wrap.appendChild(nodeRow(n, depth));
      if (S.collapsed[n.code]) return;
      const kids = children.get(n.code) || [];
      if (n.level === 0 && data.archs.length && true) {
        for (const a of data.archs) {
          if (S.arch && a.key !== S.arch) continue;
          const mine = kids.filter((k) => k.arch === a.key);
          wrap.appendChild(archHead(a, depth + 1, mine.length));
          mine.forEach((k) => visit(k, depth + 2));
        }
        const rest = kids.filter((k) => !k.arch);
        if (rest.length) {
          const head = common.cloneNode(true);
          head.style.paddingLeft = (8 + (depth + 1) * 16) + 'px';
          wrap.appendChild(head);
          rest.forEach((k) => visit(k, depth + 2));
        }
      } else kids.forEach((k) => visit(k, depth + 1));
    };
    const roots = data.nodes.filter((n) => !n.parent || !byCode.has(n.parent));
    roots.forEach((n) => visit(n, 0));
    if (!data.nodes.length) wrap.appendChild(h('p', { class: 'muted pad', text: T('empty') }));
    const first = wrap.querySelector('.row[data-code]');
    if (first && !wrap.querySelector('.row[tabindex="0"]')) { first.setAttribute('tabindex', '0'); first.setAttribute('data-focus-first', ''); }
  };
  draw();
  wrap.appendChild(h('div', { class: 'legend', text: T('chart_legend') }));

  const visible = () => [...wrap.querySelectorAll('.row[data-code]')];
  const focusRow = (el) => {
    if (!el) return;
    for (const r of wrap.querySelectorAll('.row')) r.setAttribute('tabindex', '-1');
    el.setAttribute('tabindex', '0');
    el.focus();
  };
  const current = () => (document.activeElement && document.activeElement.closest ? document.activeElement.closest('.row[data-code]') : null);
  Chart.current = {
    arrow(key) {
      const rows = visible();
      const cur = current() || rows[0];
      if (!cur) return;
      const at = rows.indexOf(cur);
      if (key === 'ArrowDown') focusRow(rows[Math.min(at + 1, rows.length - 1)]);
      else if (key === 'ArrowUp') focusRow(rows[Math.max(at - 1, 0)]);
      else if (key === 'ArrowRight') {
        const code = cur.dataset.code;
        if ((children.get(code) || []).length && S.collapsed[code]) { S.collapsed[code] = false; draw(); focusRow(wrap.querySelector('[data-code="' + code + '"]')); }
        else if (rows[at + 1] && Number(rows[at + 1].dataset.depth) > Number(cur.dataset.depth)) focusRow(rows[at + 1]);
      } else if (key === 'ArrowLeft') {
        const code = cur.dataset.code;
        if ((children.get(code) || []).length && !S.collapsed[code]) { S.collapsed[code] = true; draw(); focusRow(wrap.querySelector('[data-code="' + code + '"]')); }
        else { for (let i = at - 1; i >= 0; i -= 1) if (Number(rows[i].dataset.depth) < Number(cur.dataset.depth)) { focusRow(rows[i]); break; } }
      }
    },
    choose() {
      const cur = current();
      if (!cur) return;
      S.afterRender = () => focusPane(3);
      selectNode(cur.dataset.code);
    },
    addChild() {
      const cur = current();
      const code = cur ? cur.dataset.code : S.node;
      const level = cur ? Number(cur.dataset.level) : (byCode.get(S.node) || { level: 0 }).level;
      if (!code) { toast(T('chart_pick_first')); return; }
      if (level >= 2) { toast(T('chart_max_level')); return; }
      S.node = code;
      S.tabs[S.screen] = 'nut';
      S.afterRender = () => { if (Workspace.grid) Workspace.grid.newRow(); };
      render();
      loadTrees();
    },
  };
  ws.chart = Chart.current;
  await libraryPanel(ws);
}

/** Create placeholder sub-systems for the names an architecture lists, then show them in the chart. */
async function scaffoldArchitecture(key) {
  await guard(async () => {
    const res = await api('/api/architecture/scaffold', { body: { ma_kt: key } });
    toast(T('scaffold_done', { n: res.created.length, items: res.items_created, kept: res.existing.length }));
    S.arch = key;
    if (S.screen !== 'cay') { go('cay'); return; }
    await refreshAll();
  });
}

async function setGate(key, value, checkbox) {
  try {
    const rows = await getRows('cai_dat');
    const existing = rows.rows.find((r) => r.key === key);
    const text = value ? S.meta.values.yes : S.meta.values.no;
    const body = existing
      ? { table: 'cai_dat', op: 'update', key, record_id: existing.record_id, base_modified: existing.modified, base_fields: existing.base,
          draft_id: existing.draft || undefined, fields: { gia_tri: text } }
      : { table: 'cai_dat', op: 'create', fields: { khoa: key, gia_tri: text } };
    await api('/api/draft', { body });
    toast(T('draft_saved'));
    await refreshAll();
  } catch (e) {
    checkbox.checked = !value;
    showError(e);
  }
}

/* ---------- screens ---------- */

const SCREENS = {};

/** A row the user starts from a list or a matrix: saved at once as a draft with what we know, then opened in the grid. */
async function startRow(table, fields) {
  const idName = specOf(table).id_field;
  const f = Object.assign({}, fields);
  if (!f[idName]) f[idName] = (await api('/api/next_id', { query: { table } })).id;
  await api('/api/draft', { body: { table, op: 'create', fields: f, partial: true } });
  delete S.tableCache[table];
  S.pendingSelect = { table, key: f[idName] };
  await refreshAll();
}

SCREENS.khoi_tao = async (ws) => {
  const st = S.st || (await loadState());
  const box = ws.p3;
  ws.t2 = T('p2_settings');
  ws.t3 = T('nav_khoi_tao');
  ws.p2.appendChild(h('p', { class: 'muted pad', text: T('settings_hint') }));
  const f = {};
  const row = (key, el) => { f[key] = el; return [h('label', { for: 's-' + key, text: T('set_' + key) }), el]; };
  const url = h('input', { id: 's-teable_url', type: 'text', value: st.teable_url || '' });
  const token = h('input', { id: 's-token', type: 'password', autocomplete: 'off', placeholder: st.has_token ? T('token_saved') : '' });
  const user = h('input', { id: 's-user', type: 'text', value: st.user || '' });
  const role = h('select', { id: 's-role' }, h('option', { value: '', text: '' }),
    S.meta.roles.map((r) => h('option', { value: r, text: T('role_' + r), selected: r === st.role })));
  box.appendChild(h('div', { class: 'kv pad' }, row('teable_url', url), row('token', token), row('user', user), row('role', role)));
  const collect = () => ({ teable_url: url.value.trim(), token: token.value, user: user.value.trim(), role: role.value });
  box.appendChild(h('div', { class: 'toolbar pad' },
    h('button', { class: 'btn primary', type: 'button', id: 'btn-save-settings', text: T('btn_save_settings'), onclick: () => guard(async () => {
      S.st = await api('/api/settings', { body: collect() });
      toast(T('settings_saved'));
      token.value = '';
      await refreshAll();
      if (S.st.has_project) api('/api/refresh', { body: {} }).then(refreshAll).catch(showError);
    }) }),
    h('button', { class: 'btn', type: 'button', id: 'btn-test-conn', text: T('btn_test_conn'), onclick: () => guard(async () => {
      const c = collect();
      await api('/api/connection/test', { body: { teable_url: c.teable_url, token: c.token } });
      toast(T('conn_ok'));
    }) }),
    h('button', { class: 'btn', type: 'button', id: 'btn-reload-trees', text: T('btn_reload_trees'), onclick: () => guard(async () => {
      await api('/api/trees/reload', { body: {} });
      toast(T('trees_reloaded'));
      await loadTrees();
    }) })));

  box.appendChild(h('h2', { class: 'pad', text: T('project_title') }));
  box.appendChild(h('p', { class: 'muted pad', text: st.has_project ? T('project_open', { id: st.base_id }) : T('project_none') }));
  const baseId = h('input', { id: 's-base_id', type: 'text' });
  const pname = h('input', { id: 's-project_name', type: 'text' });
  const space = h('input', { id: 's-space_id', type: 'text' });
  box.appendChild(h('div', { class: 'kv pad' }, row('base_id', baseId), row('project_name', pname), row('space_id', space)));
  const log = h('pre', { id: 'bootstrap-log', class: 'muted pad' });
  box.appendChild(h('div', { class: 'toolbar pad' },
    h('button', { class: 'btn primary', type: 'button', id: 'btn-bootstrap', text: T('btn_bootstrap'), onclick: () => guard(async () => {
      const res = await api('/api/bootstrap', { body: { base_id: baseId.value.trim(), project_name: pname.value.trim(), space_id: space.value.trim() } });
      log.textContent = res.log.join('\n');
      toast(T('bootstrap_done', { n: Object.keys(res.table_ids).length }));
      await refreshAll();
    }) })));
  box.appendChild(log);
  if (st.has_project) {
    box.appendChild(h('h2', { class: 'pad', text: T('project_settings') }));
    const grid = await gridFor(ws, 'cai_dat', { inline: true });
    box.appendChild(grid.bar);
    box.appendChild(grid.el);
  }
};

SCREENS.tong_quan = async (ws) => {
  const data = await api('/api/overview');
  const box = ws.p3;
  ws.t2 = T('ov_my_leaves');
  ws.t3 = T('nav_tong_quan');
  ws.p2.appendChild(data.leaves.length ? h('ul', { class: 'plain list-pane', id: 'my-leaves' }, data.leaves.map((l) =>
    h('li', { class: 'item', onclick: () => go('nut', { node: l.code }) }, h('b', { class: 'code', text: l.code }), h('span', { class: 'nm', text: l.name }), h('span', { class: 'nx', text: l.next }))))
    : h('p', { class: 'muted pad', text: T('ov_no_leaves') }));
  box.appendChild(h('div', { class: 'counters pad', id: 'counters' }, data.counters.map((c) =>
    h('div', { class: 'counter ' + (c.value ? 'bad' : 'good'), 'data-counter': c.name }, h('b', { text: String(c.value) }), c.text))));
  box.appendChild(h('h2', { class: 'pad', text: T('ov_my_warnings') + ' (' + data.warnings.length + ')' }));
  box.appendChild(data.warnings.length ? h('ul', { class: 'plain' }, data.warnings.map((w) =>
    h('li', { class: 'click', onclick: () => jumpTo(w.table, w.key) },
      h('b', { text: w.key ? withName(w.table, w.key) : tableLabel(w.table) }), ' (' + tableLabel(w.table) + ') ', w.text)))
    : h('p', { class: 'muted pad', text: T('ov_none') }));
  box.appendChild(h('p', { class: 'muted pad', text: T('ov_total_warnings', { n: data.total_warnings }) }));
  box.appendChild(h('h2', { class: 'pad', text: T('ov_my_findings') + ' (' + data.my_findings.length + ')' }));
  box.appendChild(data.my_findings.length
    ? h('ul', { class: 'plain', id: 'my-findings' }, data.my_findings.map(findingRow))
    : h('p', { class: 'muted pad', text: T('ov_none') }));
  box.appendChild(h('h2', { class: 'pad', text: T('ov_my_items') + ' (' + data.my_items.length + ')' }));
  box.appendChild(data.my_items.length
    ? h('ul', { class: 'plain', id: 'my-items' }, data.my_items.map((i) =>
      h('li', { class: 'click', 'data-item': i.key, onclick: () => jumpTo('hang_muc', i.key) },
        h('b', { text: withName('hang_muc', i.key) }), ' (' + i.cap + ') - ' + i.status)))
    : h('p', { class: 'muted pad', text: T('ov_none') }));
  box.appendChild(h('h2', { class: 'pad', text: T('ov_my_tasks') }));
  box.appendChild(data.tasks.length ? h('ul', { class: 'plain' }, data.tasks.map((t) =>
    h('li', null, h('b', { text: t.key }), ' ' + t.title + (t.due ? ' - ' + t.due : '')))) : h('p', { class: 'muted pad', text: T('ov_none') }));
};

/* ---------- weekly review (docs/designs/review-first-pilot.md) ---------- */

function canRetireFinding() {
  return S.meta.retire_roles.includes((S.st || {}).role);
}

/** One open finding with its actions: the assignee marks it done; the reviewer may also cancel it. */
function findingRow(f) {
  const bits = [f.text];
  if (f.owner) bits.push(T('rv_assigned', { who: f.owner }));
  if (f.due) bits.push(T('rv_due', { date: f.due }));
  return h('li', { 'data-finding': f.key, class: 'finding' }, h('b', { text: f.key }), ' ' + bits.join(' - ') + ' ',
    h('button', { class: 'btn small no-print', type: 'button', text: T('btn_finding_done'), onclick: () => closeFinding(f, S.meta.values.change_done) }),
    canRetireFinding()
      ? h('button', { class: 'btn small no-print', type: 'button', text: T('btn_finding_cancel'), onclick: () => closeFinding(f, S.meta.values.cancelled) })
      : null);
}

/** Close a finding with a reason appended to its text (retire with a reason, never delete). */
async function closeFinding(f, status) {
  const reason = h('textarea', { id: 'close-reason', rows: '3' });
  const err = h('div', { class: 'err' });
  modal(T('rv_close_title', { key: f.key }), [h('label', { for: 'close-reason', text: T('rv_close_reason') }), reason, err], [
    h('button', { class: 'btn', type: 'button', text: T('btn_cancel'), onclick: closeModal }),
    h('button', { class: 'btn primary', type: 'button', id: 'btn-close-ok', text: T('btn_save_draft'), onclick: async () => {
      if (!reason.value.trim()) { err.textContent = T('rv_reason_needed'); return; }
      try {
        delete S.tableCache.sai_lech;
        const rows = await getRows('sai_lech');
        const row = rows.rows.find((r) => r.key === f.key);
        if (!row) throw new Error(f.key);
        const text = (row.fields.mo_ta || f.text) + ' -- ' + T('rv_close_marker') + ': ' + reason.value.trim();
        await api('/api/draft', { body: { table: 'sai_lech', op: 'update', key: f.key, record_id: row.record_id,
          base_modified: row.modified, base_fields: row.base || row.fields, draft_id: row.draft || undefined,
          fields: { trang_thai: status, mo_ta: text }, partial: true } });
      } catch (e) { showError(e); return; }
      closeModal();
      delete S.tableCache.sai_lech;
      toast(T('draft_saved'));
      await refreshAll();
    } }),
  ]);
}

/** Ask which kind of remark it is, then save a draft finding with the row's defaults and open it in the grid below. */
function addNote(ctx, review) {
  const radio = (value, key, on) => h('label', { class: 'radio' },
    h('input', { type: 'radio', name: 'rv-kind', value, checked: on }), ' ' + T(key));
  const rule = radio('rule', 'rv_kind_rule', false);
  const judgment = radio('judgment', 'rv_kind_judgment', true);
  modal(T('btn_note'), [h('p', { class: 'muted', text: T('rv_kind') }), rule, judgment], [
    h('button', { class: 'btn', type: 'button', text: T('btn_cancel'), onclick: closeModal }),
    h('button', { class: 'btn primary', type: 'button', id: 'btn-note-ok', text: T('btn_continue'), onclick: () => guard(async () => {
      const kind = rule.querySelector('input').checked ? 'rv_tag_rule' : 'rv_tag_judgment';
      const due = new Date(Date.now() + review.cycle_days * 86400000).toISOString().slice(0, 10);
      closeModal();
      const fields = { ngay: new Date().toISOString().slice(0, 10), han: due, trang_thai: S.meta.values.change_open,
        mo_ta: '[' + T(kind) + '] ' + (ctx.code ? '[' + ctx.code + '] ' : '') };
      if (ctx.node) fields.ma_nut = ctx.node;
      if (ctx.owner) fields.nguoi_nhan = ctx.owner;
      await startRow('sai_lech', fields);
      toast(T('rv_note_started'));
    }) }),
  ]);
}

SCREENS.ra_soat = async (ws) => {
  const data = await api('/api/review');
  const box = ws.p3;
  const canEnd = (S.st || {}).role === 'system_designer';
  ws.t2 = T('rv_groups');
  ws.t3 = T('nav_ra_soat');
  const note = (ctx) => h('button', { class: 'btn small no-print', type: 'button', text: T('btn_note'), onclick: () => addNote(ctx, data) });
  ws.p2.appendChild(h('ul', { class: 'plain list-pane', id: 'review-index' }, data.groups.map((g) =>
    h('li', { class: 'item', 'data-owner': g.owner, onclick: () => {
      const sec = document.querySelector('.review-group[data-owner="' + g.owner + '"]');
      if (sec) { sec.scrollIntoView({ block: 'start' }); sec.focus(); }
    } }, h('span', { class: 'nm', text: g.owner || T('rv_group_system') }),
    h('span', { class: 'nx', text: g.leaves.length + ' / ' + g.warnings.length + ' / ' + g.changed.length })))));
  box.appendChild(h('div', { class: 'toolbar pad no-print' },
    h('button', { class: 'btn primary', type: 'button', id: 'btn-end-review', text: T('btn_end_review'), disabled: !canEnd,
      title: canEnd ? '' : T('role_needed'), onclick: () => guard(async () => {
        await api('/api/review/end', { body: {} });
        toast(T('review_ended'));
        await refreshAll();
      }) }),
    h('button', { class: 'btn', type: 'button', id: 'btn-print', text: T('btn_print'), onclick: () => window.print() }),
    h('span', { class: 'muted', text: T('rv_since', { since: data.since }) })));
  box.appendChild(h('div', { class: 'counters pad', id: 'counters' }, data.counters.map((c) =>
    h('div', { class: 'counter ' + (c.value ? 'bad' : 'good'), 'data-counter': c.name }, h('b', { text: String(c.value) }), c.text))));
  box.appendChild(h('h2', { class: 'pad', text: T('rv_findings') + ' (' + data.findings.length + ')' }));
  box.appendChild(data.findings.length ? h('ul', { class: 'plain', id: 'review-findings' }, data.findings.map(findingRow))
    : h('p', { class: 'muted pad', text: T('ov_none') }));
  for (const g of data.groups) {
    if (!g.leaves.length && !g.warnings.length && !g.changed.length && g.owner) continue;
    const sec = h('section', { class: 'review-group pad', 'data-owner': g.owner, tabindex: '-1' },
      h('h2', null, g.owner || T('rv_group_system'), ' ', note({ owner: g.owner })));
    if (g.leaves.length) {
      sec.appendChild(h('h3', { text: T('rv_leaves') }));
      sec.appendChild(h('ul', { class: 'plain' }, g.leaves.map((l) =>
        h('li', null, h('b', { text: l.code }), ' ' + l.name + ' - ' + l.next + ' ', note({ node: l.code, owner: g.owner, code: l.code })))));
    }
    if (g.warnings.length) {
      sec.appendChild(h('h3', { text: T('rv_warnings') + ' (' + g.warnings.length + ')' }));
      sec.appendChild(h('ul', { class: 'plain' }, g.warnings.map((w) =>
        h('li', null, h('b', { text: w.key ? withName(w.table, w.key) : tableLabel(w.table) }), ' (' + tableLabel(w.table) + ') ' + w.text + ' ',
          note({ node: w.node || '', owner: g.owner, code: w.key })))));
    }
    if (g.changed.length) {
      sec.appendChild(h('h3', { text: T('rv_changed') + ' (' + g.changed.length + ')' }));
      sec.appendChild(h('ul', { class: 'plain' }, g.changed.map((c) =>
        h('li', null, h('b', { text: withName(c.table, c.key) }), ' (' + tableLabel(c.table) + ') ',
          note({ node: c.node, owner: g.owner, code: c.key })))));
    }
    box.appendChild(sec);
  }
  box.appendChild(h('h2', { class: 'pad no-print', text: tableLabel('sai_lech') }));
  const grid = await gridFor(ws, 'sai_lech', { inline: true });
  box.appendChild(h('div', { class: 'no-print' }, grid.bar, grid.el));
};

/* ---------- list + grid screens ---------- */

SCREENS.yeu_cau = (ws) => listAndGrid(ws, 'yeu_cau', { side: (r) => T('n_nodes', { n: (r.extras || {}).n_nodes || 0 }) });

SCREENS.kien_truc = (ws) => listAndGrid(ws, 'kien_truc', {
  side: (r) => ((r.extras || {}).weighted === null || (r.extras || {}).weighted === undefined ? '' : String(r.extras.weighted)),
  actions: (row) => {
    const allowed = (S.st || {}).role === 'system_designer';
    const chosen = row.fields.trang_thai === S.meta.values.arch_chosen;
    return [
      h('button', { class: 'btn small', type: 'button', 'data-choose': row.key, disabled: !allowed || chosen,
        title: allowed ? '' : T('role_needed'), text: T('btn_choose'),
        onclick: () => chooseArchitecture({ key: row.key, fields: row.fields, base: row.base, record_id: row.record_id, modified: row.modified, draft: row.draft }) }),
      h('button', { class: 'btn small', type: 'button', 'data-scaffold': row.key, disabled: !row.fields.he_con_cap1 || !!row.issues.length,
        title: T('scaffold_title'), text: T('btn_scaffold'), onclick: () => scaffoldArchitecture(row.key) }),
    ];
  },
});

/** The library as a screen: every item in a table you can edit in place, with the quick placeholder at the top. */
SCREENS.thu_vien = async (ws) => {
  const name = h('input', { type: 'text', id: 'lib-new', placeholder: T('lib_new_name'), 'aria-label': T('lib_new_name'), autocomplete: 'off' });
  const who = h('input', { type: 'text', id: 'lib-who', placeholder: T('lib_who'), 'aria-label': T('lib_who'), autocomplete: 'off' });
  const make = () => guard(async () => {
    const ten = name.value.trim();
    if (!ten) { name.focus(); return; }
    const res = await api('/api/breakdown/add', { body: { new: { ten, nguoi_dien: who.value.trim() || undefined }, place: false } });
    toast(T('lib_created', { node: '', item: res.item }));
    S.pendingSelect = { table: 'hang_muc', key: res.item };
    await refreshAll();
  });
  name.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); make(); } });
  const v = S.meta.values;
  const dotOf = (row) => ({ [v.lib_placeholder]: 'r', [v.lib_filling]: 'y', [v.lib_done]: 'g' }[row.fields.trang_thai] || '');
  const bar = h('span', { class: 'lib-new' }, name, who,
    h('button', { class: 'btn small primary', type: 'button', id: 'btn-lib-make', text: T('btn_make_placeholder'), onclick: make }));
  return listAndGrid(ws, 'hang_muc', {
    dot: dotOf, barExtra: bar,
    side: (r) => (r.extras.used ? T('lib_used_n', { n: r.extras.used }) : ''),
    actions: (row) => h('button', { class: 'btn small', type: 'button', 'data-use': row.key, text: T('btn_use'), title: T('btn_use_title'),
      onclick: () => addToBreakdown({ item: row.key }, undefined, 'cay') }),
  });
};

async function chooseArchitecture(card) {
  const reason = h('textarea', { id: 'choose-reason', rows: '3' });
  reason.value = card.fields.ly_do || '';
  const err = h('div', { class: 'err' });
  modal(T('arch_choose_title', { key: card.key }), [h('label', { for: 'choose-reason', text: T('arch_reason') }), reason, err], [
    h('button', { class: 'btn', type: 'button', text: T('btn_cancel'), onclick: closeModal }),
    h('button', { class: 'btn primary', type: 'button', id: 'btn-choose-ok', text: T('btn_choose'), onclick: async () => {
      if (!reason.value.trim()) { err.textContent = T('arch_reason_needed'); return; }
      try {
        await api('/api/draft', { body: { table: 'kien_truc', op: 'update', key: card.key, record_id: card.record_id,
          base_modified: card.modified, base_fields: card.base || card.fields, draft_id: card.draft || undefined,
          fields: { trang_thai: S.meta.values.arch_chosen, ly_do: reason.value.trim() } } });
      } catch (e) { showError(e); return; }
      closeModal();
      toast(T('draft_saved'));
      await refreshAll();
    } }),
  ]);
}

SCREENS.rfq = (ws) => listAndGrid(ws, 'rfq', {});

SCREENS.moc = async (ws) => {
  const active = S.tabs.moc || 'moc';
  ws.tabs = { items: SCREEN_TABS.moc.map((k) => ({ key: k })), active, pick: (k) => { S.tabs.moc = k; render(); } };
  await listAndGrid(ws, active, {});
};

SCREENS.mua_hang = async (ws) => {
  const q = await api('/api/sourcing');
  const grid = await listAndGrid(ws, 'mua_hang', {});
  ws.t2 = T('src_queue') + ' (' + q.queue.length + ')';
  ws.p2.textContent = '';
  ws.p2.appendChild(q.queue.length ? h('ul', { class: 'plain list-pane', id: 'src-queue' }, q.queue.map((c) =>
    h('li', { class: 'item', 'data-uv': c.uv, onclick: () => guard(() => startRow('mua_hang', { ma_uv: c.uv, tien_te: c.currency || undefined })) },
      h('b', { class: 'code', text: c.uv }), h('span', { class: 'nm', text: withName('nut', c.node) + ' - ' + [c.hang, c.model].filter(Boolean).join(' ') }),
      h('span', { class: 'nx', text: c.price !== null && c.price !== undefined ? c.price + ' ' + c.currency : '' }))))
    : h('p', { class: 'muted pad', text: T('src_queue_empty') }));
  ws.t3 = T('src_rows');
  return grid;
};

/* ---------- node workspace: chart in pane 2, tabs in pane 3 ---------- */

function compareBlock(cmp, node) {
  const ct = h('table', { class: 'grid compact', id: 'compare' });
  ct.appendChild(h('thead', null, h('tr', null, h('th', { class: 'ro', text: T('col_spec') }),
    cmp.candidates.map((uv) => h('th', { class: 'ro' }, withName('ung_vien', uv), h('div', { class: cmp.pass[uv] ? 'pass' : 'unchecked', text: cmp.results[uv] }))))));
  ct.appendChild(h('tbody', null, cmp.rows.map((r) => h('tr', { 'data-spec': r.ts },
    h('td', null, h('b', { text: r.ts }), ' ' + r.name, h('div', { class: 'muted', text: [r.min, r.max].map(num).join(' ... ') + ' ' + r.unit + ' (' + r.muc + ')' })),
    r.cells.map((c) => h('td', { class: 'cell', 'data-cell': c.uv + '|' + r.ts, title: [c.quote, c.page].filter(Boolean).join(' / '),
      onclick: () => (Workspace.grid ? checkCell(c.uv, r.ts) : null) },
      h('span', { class: c.state === 'pass' ? 'pass' : (c.state === 'fail' ? 'fail' : 'unchecked'), text: c.state === 'unchecked' ? '?' : num(c.value) || T('state_' + c.state) }),
      c.draft ? h('span', { class: 'badge draft', text: T('draft_mark') }) : null))))));
  return h('div', { class: 'tablewrap' }, ct);
}

/** A cell of the comparison: go to its row in the table below, or start the row when nobody has checked it yet. */
async function checkCell(uv, ts) {
  const key = uv + '|' + ts;
  const rows = await getRows('doi_chieu', { node: S.node });
  if (rows.rows.some((r) => r.key === key)) {
    S.pendingSelect = { table: 'doi_chieu', key };
    S.tabs[S.screen] = 'doi_chieu';
    render();
  } else {
    S.tabs[S.screen] = 'doi_chieu';
    await guard(() => startRow('doi_chieu', { khoa: key, ma_uv: uv, ma_ts: ts }));
  }
}

function allocMatrix(data) {
  const t = h('table', { class: 'grid compact', id: 'alloc-matrix' });
  t.appendChild(h('thead', null, h('tr', null,
    h('th', { class: 'ro', text: T('col_requirement') }),
    data.nodes.map((n) => h('th', { class: 'ro', title: withName('nut', n), text: withName('nut', n) })),
    h('th', { class: 'ro', text: T('col_budget_total') }), h('th', { class: 'ro', text: T('col_margin') }))));
  const body = h('tbody');
  for (const r of data.requirements) {
    const b = data.budgets[r.code];
    const tr = h('tr', { 'data-req': r.code }, h('td', { title: r.text }, h('b', { text: r.code }), ' ' + r.text.slice(0, 28)));
    for (const n of data.nodes) {
      const cell = data.cells[r.code + '|' + n];
      const td = h('td', { class: 'cell' + (cell && cell.draft ? ' over' : ''), 'data-cell': r.code + '|' + n,
        title: cell ? cell.key + ' ' + cell.kieu : T('alloc_create'),
        onclick: () => {
          if (cell) { S.pendingSelect = { table: 'phan_bo', key: cell.key }; S.tabs[S.screen] = 'phan_bo'; render(); }
          else guard(() => startRow('phan_bo', { ma_yc: r.code, ma_nut: n }));
        } });
      td.textContent = cell ? (cell.value !== null && cell.value !== undefined ? String(cell.value) : '•') : '';
      tr.appendChild(td);
    }
    tr.appendChild(h('td', { class: 'num' + (b && b.over ? ' fail' : ''), text: b ? String(b.total) : '' }));
    tr.appendChild(h('td', { class: 'num' + (b && b.over ? ' fail' : ''), text: b && b.margin !== null ? String(b.margin) : '' }));
    body.appendChild(tr);
  }
  t.appendChild(body);
  return h('div', { class: 'tablewrap' }, t);
}

async function hierarchy(ws) {
  await chartPane(ws);
  const screen = S.screen;
  const tabs = SCREEN_TABS[screen];
  const active = S.tabs[screen] || DEFAULT_TAB[screen];
  const counts = await Promise.all(tabs.map((t) => getRows(t, { node: S.node }).then((d) => d.rows.length)));
  ws.tabs = { items: tabs.map((k, i) => ({ key: k, count: counts[i] })), active, pick: (k) => { S.tabs[screen] = k; render(); } };
  let info = null;
  if (S.node) info = await api('/api/node', { query: { code: S.node } });
  ws.t3 = S.node && info && info.node
    ? T('p3_node', { node: withName('nut', S.node) }) + ' - ' + (info.node.phu_trach || T('none')) + ' - ' + info.node.next
    : T('p3_all_nodes');
  const fields = specOf(active).fields;
  const prefill = {};
  if (S.node) { if (fields.ma_cha) prefill.ma_cha = S.node; else if (fields.ma_nut) prefill.ma_nut = S.node; }
  if (active === 'doi_chieu' && info && info.compare && info.compare.candidates.length && info.compare.rows.length) {
    ws.p3.appendChild(compareBlock(info.compare, S.node));
  }
  if (active === 'phan_bo') ws.p3.appendChild(allocMatrix(await api('/api/alloc')));
  const grid = await gridFor(ws, active, { node: S.node, prefill, onChange: () => { /* counts refresh on the next render */ } });
  ws.p3.appendChild(grid.el);
}
SCREENS.cay = hierarchy;
SCREENS.phan_bo = hierarchy;
SCREENS.nut = hierarchy;

/* ---------- commit ---------- */

SCREENS.commit = async (ws) => {
  const data = await api('/api/drafts');
  const st = S.st || (await loadState());
  const box = ws.p3;
  ws.t2 = T('nav_commit') + ' (' + data.drafts.length + ')';
  ws.t3 = T('nav_commit');
  ws.p2.appendChild(data.drafts.length ? h('ul', { class: 'plain list-pane', id: 'draft-index' }, data.drafts.map((d) =>
    h('li', { class: 'item', 'data-draft': d.id, onclick: () => jumpTo(d.table, d.key) },
      h('span', { class: 'dot ' + (d.valid ? 'g' : 'r') }), h('span', { class: 'nm', text: tableLabel(d.table) + ' ' + withName(d.table, d.key) }), h('span', { class: 'nx', text: T('op_' + d.op) }))))
    : h('p', { class: 'muted pad', text: T('drafts_empty') }));
  const results = h('div', { id: 'commit-results', class: 'pad' });
  const btn = h('button', { class: 'btn primary', type: 'button', id: 'btn-commit', text: T('btn_commit'), 'data-focus-first': true,
    disabled: !st.can_commit || !data.drafts.length, title: st.can_commit ? '' : T('commit_disabled'),
    onclick: () => runCommit(results) });
  box.appendChild(h('div', { class: 'toolbar pad' }, btn, st.can_commit ? null : h('span', { class: 'err', text: T('commit_disabled') })));
  if (!data.drafts.length) box.appendChild(h('p', { class: 'muted pad', text: T('drafts_empty') }));
  else {
    const t = h('table', { class: 'grid', id: 'draft-list' });
    t.appendChild(h('thead', null, h('tr', null, [T('col_table'), T('col_key'), T('col_op'), T('col_state'), ''].map((x) => h('th', { class: 'ro', text: x })))));
    t.appendChild(h('tbody', null, data.drafts.map((d) => h('tr', { 'data-draft': d.id, onclick: () => jumpTo(d.table, d.key) },
      h('td', { text: tableLabel(d.table) }), h('td', { text: d.key }), h('td', { text: T('op_' + d.op) }),
      h('td', { class: d.valid ? 'ok' : 'err', text: d.valid ? T('valid') : d.issues.map((i) => fieldLabel(d.table, i.field) + ': ' + i.message).join('; ') }),
      h('td', null, h('button', { class: 'btn small', type: 'button', 'data-discard': d.id, text: T('btn_discard'), onclick: (ev) => { ev.stopPropagation(); discardDraft(d); } }))))));
    box.appendChild(h('div', { class: 'tablewrap' }, t));
  }
  box.appendChild(results);
};

/** The top bar button and Ctrl+Enter: open Commit with its button ready. Nothing is sent until that button is pressed. */
function commitNow() {
  S.afterRender = () => { const b = document.getElementById('btn-commit'); if (b) b.focus(); };
  go('commit');
}

async function discardDraft(d) {
  if (!window.confirm(T('confirm_discard', { key: d.key }))) return;
  await guard(async () => {
    await api('/api/draft/discard', { body: { draft_id: d.id } });
    delete S.tableCache[d.table];
    await refreshAll();
  });
}

async function runCommit(out) {
  out.textContent = '';
  out.appendChild(h('p', { class: 'muted', text: T('commit_running') }));
  let res;
  try { res = await api('/api/commit', { body: {} }); } catch (e) { out.textContent = ''; showError(e); await loadState(); return; }
  S.tableCache = {};
  out.textContent = '';
  const list = h('ul', { class: 'plain', id: 'commit-lines' });
  for (const r of res.results) {
    const li = h('li', { 'data-status': r.status, class: r.status === 'committed' ? 'ok' : 'err' },
      h('b', { text: tableLabel(r.table) + ' ' + r.key }), ' - ' + T('res_' + r.status) + (r.message ? ': ' + r.message : ''));
    if (r.status === 'conflict' && r.conflict) li.appendChild(h('button', { class: 'btn small', type: 'button', 'data-resolve': r.draft_id, text: T('btn_resolve'), onclick: () => conflictDialog(r) }));
    if (r.status === 'stale' && r.stale) li.appendChild(h('button', { class: 'btn small', type: 'button', 'data-resolve': r.draft_id, text: T('btn_resolve'), onclick: () => staleDialog(r) }));
    list.appendChild(li);
  }
  out.appendChild(list);
  await loadState();
  markNav();
  const unresolved = res.results.some((r) => r.status === 'conflict' || r.status === 'stale');
  if (!unresolved) { toast(res.ok ? T('commit_ok') : T('commit_partial')); }
  const first = res.results.find((r) => r.status === 'conflict' && r.conflict);
  if (first) conflictDialog(first);
  else { const st = res.results.find((r) => r.status === 'stale' && r.stale); if (st) staleDialog(st); }
}

function conflictDialog(r) {
  const c = r.conflict;
  const input = h('input', { id: 'conflict-new-id', type: 'text', value: c.proposed_id || '' });
  const err = h('div', { class: 'err' });
  modal(T('conflict_title'), [
    h('p', { text: T('conflict_text', { id: c.id, by: c.taken_by || T('unknown'), at: c.taken_at || T('unknown') }) }),
    h('label', { for: 'conflict-new-id', text: T('conflict_new_id') }), input, err,
  ], [
    h('button', { class: 'btn', type: 'button', text: T('btn_later'), onclick: closeModal }),
    h('button', { class: 'btn primary', type: 'button', id: 'btn-accept-id', text: T('btn_accept_id'), onclick: async () => {
      try {
        const res = await api('/api/commit/accept', { body: { draft_id: r.draft_id, new_id: input.value.trim() } });
        closeModal();
        toast(T('conflict_renamed', { n: res.rewritten }));
        await refreshAll();
      } catch (e) { err.textContent = (e.err && e.err.detail) || String(e); }
    } }),
  ]);
}

function staleDialog(r) {
  const info = r.stale;
  const choices = {};
  const rows = info.fields.map((f) => {
    choices[f.field] = 'mine';
    const name = 'stale-' + f.field;
    const radio = (v, label) => h('label', null, h('input', { type: 'radio', name, value: v, checked: v === 'mine', onchange: () => { choices[f.field] = v; } }), ' ' + label);
    return h('tr', { 'data-field': f.field },
      h('td', { text: fieldLabel(info.table, f.field) }), h('td', { text: String(num(f.base)) }),
      h('td', null, radio('mine', String(num(f.mine)))), h('td', null, radio('theirs', String(num(f.theirs)))));
  });
  const t = h('table', { class: 'grid' }, h('thead', null, h('tr', null, [T('col_field'), T('stale_base'), T('stale_mine'), T('stale_theirs')].map((x) => h('th', { class: 'ro', text: x })))), h('tbody', null, rows));
  modal(T('stale_title', { key: info.key }), [h('p', { text: T('stale_text', { by: info.modified_by || T('unknown') }) }), t], [
    h('button', { class: 'btn', type: 'button', text: T('btn_later'), onclick: closeModal }),
    h('button', { class: 'btn primary', type: 'button', id: 'btn-apply-stale', text: T('btn_apply_choice'), onclick: async () => {
      await guard(async () => {
        await api('/api/commit/stale', { body: { draft_id: r.draft_id, choices } });
        closeModal();
        toast(T('stale_applied'));
        await refreshAll();
      });
    } }),
  ]);
}

/* ---------- start ---------- */

async function start() {
  try {
    S.meta = await api('/api/meta');
  } catch (e) {
    document.getElementById('p3-body').textContent = String((e.err && e.err.detail) || e);
    return;
  }
  for (const el of document.querySelectorAll('[data-i]')) el.textContent = T(el.dataset.i);
  for (const el of document.querySelectorAll('[data-i-title]')) el.title = T(el.dataset.iTitle);
  for (const el of document.querySelectorAll('[data-i-label]')) el.setAttribute('aria-label', T(el.dataset.iLabel));
  document.getElementById('panel-toggle').addEventListener('click', () => setPanel(S.panel === 'strip' ? 'open' : 'strip'));
  document.getElementById('panel-wide').addEventListener('click', widenPanel);
  document.getElementById('panel-strip').addEventListener('click', () => setPanel('open'));
  let saved = 'open';
  try {
    saved = localStorage.getItem('t3_panel') || 'open';
    for (const key of ['--p1w', '--p2w', '--p4w']) {
      const w = localStorage.getItem('t3' + key);
      if (w) document.documentElement.style.setProperty(key, w + 'px');
    }
  } catch (e) { /* no storage: keep the default widths */ }
  setPanel(saved);
  buildNav();
  const st = await loadState();
  S.treeName = st ? st.tree : '';
  S.screen = st ? st.default_screen : 'khoi_tao';
  await render();
  await loadTrees();
  if (st && st.has_project && st.connection.state === 'online') {
    api('/api/refresh', { body: {} }).then(() => { S.tableCache = {}; return refreshAll(); }).catch(() => { /* offline or refused: the status bar shows why */ });
  }
  setInterval(() => { loadState(); }, 10000);
}

window.addEventListener('load', start);
