'use strict';
/* T3 Desk UI. Plain JavaScript, no framework, no network except this server's own /api.
 * All visible text comes from labels (labels_vi.yaml via /api/meta): use the T helper. */

const SESSION = document.querySelector('meta[name="session"]').content;
const S = {
  meta: null, st: null, screen: 'khoi_tao', node: '', owner: '', treeName: '', treeData: null, fnode: '',
  names: {}, panel: 'open', renderId: 0, sort: {}, lastLeaf: '', form: null, tableCache: {},
};

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
  if (!isError) toastTimer = setTimeout(() => { box.hidden = true; }, 4000);
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

/* ---------- shell: nav, status bar, panel ---------- */

function buildNav() {
  const nav = document.getElementById('nav');
  nav.textContent = '';
  for (const key of S.meta.screens) {
    const b = h('button', { type: 'button', 'data-screen': key, text: T('nav_' + key), onclick: () => go(key) });
    if (key === 'commit') b.appendChild(h('span', { class: 'badge draft', id: 'nav-drafts', text: '0' }));
    nav.appendChild(b);
  }
}

function markNav() {
  for (const b of document.querySelectorAll('#nav button')) {
    if (b.dataset.screen === S.screen) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  }
  const badge = document.getElementById('nav-drafts');
  if (badge && S.st) badge.textContent = String(S.st.drafts);
}

function renderStatus() {
  const st = S.st;
  const bar = document.getElementById('status');
  bar.textContent = '';
  if (!st) return;
  const conn = st.connection;
  const roleName = st.role ? T('role_' + st.role) : T('none');
  const connText = T('conn_' + conn.state) + (conn.state === 'offline' && st.cache_age_seconds !== null
    ? ' - ' + T('cache_age', { age: fmtAge(st.cache_age_seconds) }) : '');
  bar.appendChild(h('span', { id: 'st-project', text: T('st_project') + ': ' + (st.project || T('none')) }));
  bar.appendChild(h('span', { id: 'st-user', text: T('st_user') + ': ' + (st.user || T('none')) + ' (' + roleName + ')' }));
  bar.appendChild(h('span', { id: 'st-conn', class: 'state-' + conn.state, text: T('st_teable') + ': ' + connText, title: conn.message || '' }));
  bar.appendChild(h('span', { id: 'st-drafts', text: T('st_drafts') + ': ' + st.drafts }));
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

function setPanel(mode) {
  S.panel = mode;
  document.getElementById('shell').dataset.panel = mode;
  document.getElementById('panel-toggle').textContent = mode === 'strip' ? T('panel_open') : T('panel_collapse');
  try { localStorage.setItem('t3_panel', mode); } catch (e) { /* storage may be blocked: the panel still works */ }
}

function widenPanel() {
  setPanel(S.panel === 'open' ? 'wide' : (S.panel === 'wide' ? 'open' : 'open'));
}

async function loadTrees() {
  let data;
  try { data = await api('/api/trees', { query: { node: S.node } }); } catch (e) { showError(e); return; }
  S.treeData = data;
  if (!S.treeName || !data.trees[S.treeName]) S.treeName = data.first;
  drawPanel();
}

function drawPanel() {
  const data = S.treeData;
  if (!data) return;
  const info = document.getElementById('panel-node');
  info.textContent = '';
  info.appendChild(document.createTextNode(S.node ? T('panel_node', { node: S.node }) : T('panel_no_node')));
  if (S.node) info.appendChild(h('button', { class: 'btn', type: 'button', text: T('panel_clear_node'), onclick: () => selectNode('') }));
  const tabs = document.getElementById('tree-tabs');
  tabs.textContent = '';
  for (const name of S.meta.tree_names) {
    tabs.appendChild(h('button', {
      type: 'button', role: 'tab', 'data-tree': name, 'aria-selected': String(name === S.treeName),
      text: T('tree_' + name), onclick: () => { S.treeName = name; drawPanel(); },
    }));
  }
  const tree = data.trees[S.treeName];
  if (!tree) return;
  drawHelp(tree, data.guide || []);
  TreeView.draw(document.getElementById('tree-view'), tree, {
    yesText: T('answer_yes'), noText: T('answer_no'),
    onAction: (screen) => go(screen, { node: S.node }),
    onLeaf: (el) => {
      const sig = S.treeName + ':' + tree.leaf.index + ':' + tree.leaf.answer;
      if (sig !== S.lastLeaf) { S.lastLeaf = sig; el.scrollIntoView({ block: 'center', inline: 'nearest' }); }
    },
  });
}

/* guidance under the tree: help of the question you are at, every step's help, and the glossary */
function drawHelp(tree, guide) {
  const box = document.getElementById('tree-help');
  box.textContent = '';
  const here = tree.leaf ? tree.questions.find((q) => q.index === tree.leaf.index) : null;
  if (here && here.help) box.appendChild(h('div', { class: 'here-help' }, h('b', { text: T('guide_here') + ': ' }), here.help));
  const steps = tree.questions.filter((q) => q.help);
  if (steps.length) {
    box.appendChild(h('details', null, h('summary', { text: T('guide_all') }),
      steps.map((q) => h('p', null, h('b', { text: q.q + ' ' }), q.help))));
  }
  if (guide.length) {
    box.appendChild(h('details', { id: 'guide-glossary' }, h('summary', { text: T('guide_glossary') }),
      guide.map((g) => h('p', null, h('b', { text: g.term + ': ' }), g.text))));
  }
}

async function selectNode(code) {
  S.node = code;
  await loadTrees();
  if (S.screen === 'nut') render();
}

/* ---------- navigation ---------- */

function go(screen, opts) {
  const o = opts || {};
  S.screen = screen;
  S.fnode = o.node || '';
  if (o.node) S.node = o.node;
  S.owner = o.owner || '';
  render();
  loadTrees();
}

let rendering = 0;
async function render() {
  const id = ++S.renderId;
  rendering = id;
  markNav();
  const main = document.getElementById('main');
  const fn = SCREENS[S.screen] || SCREENS.khoi_tao;
  const box = h('div');
  try {
    await fn(box);
  } catch (e) {
    box.textContent = '';
    box.appendChild(h('p', { class: 'err', text: T('err_screen') }));
    showError(e);
  }
  if (id !== S.renderId) return;
  main.textContent = '';
  main.appendChild(box);
}

async function refreshAll() {
  await loadState();
  await render();
  await loadTrees();
}

/* ---------- generic table ---------- */

async function getRows(table, filter) {
  const q = { table };
  if (filter && filter.node) q.node = filter.node;
  if (filter && filter.owner) q.owner = filter.owner;
  return api('/api/rows', { query: q });
}

function visibleColumns(table, rows) {
  const spec = specOf(table);
  const names = Object.keys(spec.fields);
  const idName = spec.id_field;
  const cols = [idName];
  for (const n of names) {
    if (n === idName || spec.fields[n].type === 'longtext') continue;
    if (cols.length < S.meta.list_columns) cols.push(n);
  }
  return cols;
}

function settingLabel(key) {
  return ((S.meta.labels.settings_keys || {})[key]) || '';
}

function isRateKey(table, key) {
  const cfg = S.meta.schema.exchange_rates || {};
  return table === cfg.table && !!cfg.key_prefix && String(key || '').startsWith(cfg.key_prefix);
}

/* "N1 - Propulsion": a code is never shown alone when its name is known */
function withName(ref, code) {
  const nm = ((S.names || {})[ref] || {})[code];
  return nm ? code + ' - ' + nm : code;
}

function cellText(table, name, value) {
  if (value === null || value === undefined) return '';
  const fs = (specOf(table).fields || {})[name];
  if (fs && fs.ref && value !== '') {
    const sep = fs.multi || null;
    return (sep ? String(value).split(sep) : [String(value)]).map((c) => withName(fs.ref, c.trim())).join('; ');
  }
  if (table === 'cai_dat' && name === 'khoa' && settingLabel(value)) return settingLabel(value) + ' (' + value + ')';
  return String(value);
}

function sortRows(table, rows) {
  const s = S.sort[table];
  if (!s) return rows;
  const get = (r) => (s.extra ? r.extras[s.col] : r.fields[s.col]);
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

async function openRow(table, key) {
  const data = await getRows(table);
  const row = data.rows.find((r) => r.key === key);
  if (row) openForm({ table, row });
}

function tableView(table, data, opts) {
  const o = opts || {};
  const spec = specOf(table);
  const cols = visibleColumns(table, data.rows);
  const extraNames = [...new Set(data.rows.flatMap((r) => Object.keys(r.extras)))];
  const wrap = h('div', { class: 'tablewrap' });
  const t = h('table', { class: 'grid', 'data-table': table });
  const head = h('tr');
  head.appendChild(h('th', { class: 'nosort', text: '' }));
  const mkTh = (col, extra, label) => h('th', {
    text: label + (S.sort[table] && S.sort[table].col === col && !!S.sort[table].extra === extra ? (S.sort[table].dir > 0 ? ' ▲' : ' ▼') : ''),
    onclick: () => {
      const cur = S.sort[table];
      S.sort[table] = { col, extra, dir: cur && cur.col === col ? -cur.dir : 1 };
      render();
    },
  });
  cols.forEach((c) => head.appendChild(mkTh(c, false, fieldLabel(table, c))));
  extraNames.forEach((c) => head.appendChild(mkTh(c, true, T('extra_' + c))));
  t.appendChild(h('thead', null, head));
  const body = h('tbody');
  for (const row of sortRows(table, data.rows)) {
    const tr = h('tr', { class: row.draft ? 'is-draft' : '', 'data-key': row.key, onclick: () => (o.onRow ? o.onRow(row) : openForm({ table, row })) });
    const first = h('td');
    if (row.draft) first.appendChild(h('span', { class: 'badge draft', text: T('draft_mark') }));
    if (row.warnings.length) first.appendChild(h('span', { class: 'badge warn', title: row.warnings.join('\n'), text: '! ' + row.warnings.length }));
    tr.appendChild(first);
    cols.forEach((c) => {
      const v = row.fields[c];
      const td = h('td', { class: typeof v === 'number' ? 'num' : '' });
      if (o.link && o.link === c && /^https?:\/\//.test(String(v || ''))) {
        td.appendChild(h('a', { href: v, target: '_blank', rel: 'noopener', text: String(v), onclick: (ev) => ev.stopPropagation() }));
      } else td.textContent = cellText(table, c, v);
      tr.appendChild(td);
    });
    extraNames.forEach((c) => tr.appendChild(h('td', { text: num(row.extras[c]) })));
    body.appendChild(tr);
  }
  t.appendChild(body);
  wrap.appendChild(t);
  if (!data.rows.length) wrap.appendChild(h('p', { class: 'muted', text: T('empty') }));
  return wrap;
}

function filterBar(table, data, onChange) {
  const nodeSel = h('select', { id: 'f-node', 'aria-label': T('filter_node') },
    h('option', { value: '', text: T('filter_node') + ': ' + T('all') }),
    data.nodes.map((n) => h('option', { value: n, text: withName('nut', n), selected: n === S.fnode })));
  const ownerSel = h('select', { id: 'f-owner', 'aria-label': T('filter_owner') },
    h('option', { value: '', text: T('filter_owner') + ': ' + T('all') }),
    data.owners.map((n) => h('option', { value: n, text: n, selected: n === S.owner })));
  nodeSel.addEventListener('change', () => { S.fnode = nodeSel.value; onChange(); });
  ownerSel.addEventListener('change', () => { S.owner = ownerSel.value; onChange(); });
  return [nodeSel, ownerSel];
}

async function exportCsv(table) {
  await guard(async () => {
    const q = { table };
    if (S.fnode) q.node = S.fnode;
    if (S.owner) q.owner = S.owner;
    const res = await api('/api/csv', { query: q });
    const blob = new Blob([res.text], { type: 'text/csv;charset=utf-8' });
    const a = h('a', { href: URL.createObjectURL(blob), download: res.filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(T('csv_done', { name: res.filename }));
  });
}

async function tableScreen(box, table, opts) {
  const o = opts || {};
  const data = await getRows(table, { node: S.fnode, owner: S.owner });
  const bar = h('div', { class: 'toolbar' });
  bar.appendChild(h('button', { class: 'btn primary', type: 'button', id: 'btn-new-' + table, text: T('btn_new'),
    onclick: () => openForm({ table, prefill: o.prefill || {} }) }));
  filterBar(table, data, () => render()).forEach((e) => bar.appendChild(e));
  bar.appendChild(h('button', { class: 'btn', type: 'button', text: T('btn_csv'), onclick: () => exportCsv(table) }));
  bar.appendChild(h('span', { class: 'muted grow', text: T('cache_age', { age: fmtAge(data.age) }) }));
  box.appendChild(bar);
  box.appendChild(tableView(table, data, o));
  return data;
}

/* ---------- forms generated from schema.yaml ---------- */

async function idChoices(ref) {
  if (!S.tableCache[ref]) {
    const data = await getRows(ref);
    S.tableCache[ref] = data.rows.map((r) => r.key);
  }
  return S.tableCache[ref];
}

function closeModal() {
  document.getElementById('modal-root').textContent = '';
  S.form = null;
}

function modal(title, bodyEl, buttons) {
  const root = document.getElementById('modal-root');
  root.textContent = '';
  const dlg = h('div', { class: 'dialog', role: 'dialog', 'aria-modal': 'true' },
    h('header', { text: title }), h('div', { class: 'body' }, bodyEl), h('footer', null, buttons));
  root.appendChild(h('div', { class: 'overlay' }, dlg));
  const first = dlg.querySelector('input:not([readonly]), select, textarea');
  if (first) first.focus();
  return dlg;
}

function widget(table, name, spec, value, refIds, readonly) {
  let el;
  const id = 'fld-' + name;
  if (spec.type === 'choice') {
    el = h('select', { id, name }, h('option', { value: '', text: '' }),
      spec.choices.map((c) => h('option', { value: c, text: c, selected: c === value })));
  } else if (spec.type === 'longtext') {
    el = h('textarea', { id, name, rows: '2' });
    el.value = value === undefined || value === null ? '' : value;
  } else if (spec.type === 'number') {
    el = h('input', { id, name, type: 'number', step: 'any' });
    el.value = value === undefined || value === null ? '' : value;
  } else if (spec.type === 'date') {
    el = h('input', { id, name, type: 'date' });
    el.value = value ? String(value).slice(0, 10) : '';
  } else {
    el = h('input', { id, name, type: 'text' });
    el.value = value === undefined || value === null ? '' : value;
    if (spec.ref && refIds) {
      const dl = h('datalist', { id: 'dl-' + name }, refIds.map((r) => h('option', { value: r, label: withName(spec.ref, r), text: withName(spec.ref, r) })));
      el.setAttribute('list', 'dl-' + name);
      el._datalist = dl;
    }
  }
  if (readonly) { el.setAttribute('readonly', ''); if (el.tagName === 'SELECT') el.setAttribute('disabled', ''); }
  return el;
}

function readWidget(spec, el) {
  const raw = el.value;
  if (raw === '') return '';
  if (spec.type === 'number') return Number(raw);
  return raw;
}

async function openForm(opts) {
  const table = opts.table;
  const spec = specOf(table);
  const idName = spec.id_field;
  const row = opts.row || null;
  const isCreateDraft = row && row.draft_op === 'create';
  const isUpdate = !!row && !isCreateDraft;
  const values = Object.assign({}, opts.prefill || {}, row ? row.fields : {});
  const refIds = {};
  for (const n in spec.fields) {
    const ref = spec.fields[n].ref;
    if (ref && !refIds[ref]) refIds[ref] = await idChoices(ref).catch(() => []);
  }
  if (!row && spec.id.kind !== 'composite' && spec.id.kind !== 'key' && !values[idName]) {
    try {
      const q = { table };
      if (values.ma_cha) q.parent = values.ma_cha;
      const p = await api('/api/next_id', { query: q });
      if (p.id) values[idName] = p.id;
    } catch (e) { /* no proposal for this kind or parent: the user types the ID */ }
  }
  const grid = h('div', { class: 'form-grid' });
  const inputs = {};
  for (const name in spec.fields) {
    const fs = spec.fields[name];
    if (spec.id.kind === 'composite' && name === idName) continue; // built by the app from other fields
    const readonly = name === idName && isUpdate;
    const el = widget(table, name, fs, values[name], refIds[fs.ref], readonly);
    inputs[name] = el;
    let labelText = fieldLabel(table, name);
    if (table === 'cai_dat' && name === 'gia_tri' && settingLabel(values.khoa)) labelText = settingLabel(values.khoa);
    if (isRateKey(table, values.khoa) && name === 'gia_tri') { el.setAttribute('inputmode', 'decimal'); el.setAttribute('placeholder', '27000'); }
    const label = h('label', { for: 'fld-' + name, text: labelText + (fs.required ? ' *' : '') });
    const cell = h('div', { class: 'f' + (fs.type === 'longtext' ? ' wide' : ''), 'data-field': name }, label, el, el._datalist || null);
    if (name === idName && spec.id.example) cell.appendChild(h('span', { class: 'muted', text: T('id_example', { ex: spec.id.example }) }));
    if (fs.multi) cell.appendChild(h('span', { class: 'muted', text: T('multi_hint', { sep: fs.multi }) }));
    if (fs.ref) {  // show the name of the chosen code(s) under the field, updated as the user types
      const hint = h('span', { class: 'muted ref-name' });
      const show = () => { hint.textContent = el.value ? cellText(table, name, el.value) : ''; };
      el.addEventListener('input', show);
      el.addEventListener('change', show);
      show();
      cell.appendChild(hint);
    }
    grid.appendChild(cell);
  }
  const msg = h('div', { class: 'err', id: 'form-error' });
  const save = async () => {
    msg.textContent = '';
    for (const c of grid.querySelectorAll('.f')) { c.classList.remove('bad'); const w = c.querySelector('.why'); if (w) w.remove(); }
    const fields = {};
    for (const name in inputs) fields[name] = readWidget(spec.fields[name], inputs[name]);
    if (spec.id.kind === 'composite') {
      fields[idName] = spec.id.parts.map((p) => fields[p] || '').join(spec.id.separator);
    }
    let body;
    if (isUpdate) {
      const base = row.base || row.fields;
      const changed = {};
      for (const k in fields) {
        if (k === idName) continue;
        const a = fields[k] === '' ? null : fields[k];
        const b = base[k] === undefined ? null : base[k];
        if (String(a) !== String(b)) changed[k] = fields[k];
      }
      if (!Object.keys(changed).length) { msg.textContent = T('nothing_changed'); return; }
      body = { table, op: 'update', key: row.key, record_id: row.record_id, base_modified: row.modified, base_fields: base, fields: changed, draft_id: row.draft || undefined };
    } else {
      body = { table, op: 'create', fields, draft_id: isCreateDraft ? row.draft : undefined };
    }
    try {
      await api('/api/draft', { body });
    } catch (e) {
      const err = e instanceof ApiFail ? e.err : {};
      if (err.code === 'invalid' && err.issues) {
        msg.textContent = T('err_invalid');
        for (const issue of err.issues) {
          const cell = grid.querySelector('[data-field="' + issue.field + '"]');
          if (cell) { cell.classList.add('bad'); cell.appendChild(h('span', { class: 'why', text: T('v_' + issue.code) + ' - ' + issue.message })); }
        }
      } else showError(e);
      return;
    }
    delete S.tableCache[table];
    closeModal();
    toast(T('draft_saved'));
    await refreshAll();
  };
  S.form = { save };
  const title = (row ? (isCreateDraft ? T('form_edit_draft') : T('form_edit')) : T('form_new')) + ': ' + tableLabel(table);
  modal(title, [grid, msg], [
    h('button', { class: 'btn', type: 'button', id: 'form-cancel', text: T('btn_cancel'), onclick: closeModal }),
    h('button', { class: 'btn primary', type: 'button', id: 'form-save', text: T('btn_save_draft'), onclick: save }),
  ]);
}

/* ---------- screens ---------- */

const SCREENS = {};

SCREENS.khoi_tao = async (box) => {
  const st = S.st || (await loadState());
  box.appendChild(h('h1', { text: T('nav_khoi_tao') }));
  const f = {};
  const row = (key, el) => { f[key] = el; return [h('label', { for: 's-' + key, text: T('set_' + key) }), el]; };
  const url = h('input', { id: 's-teable_url', type: 'text', value: st.teable_url || '' });
  const token = h('input', { id: 's-token', type: 'password', autocomplete: 'off', placeholder: st.has_token ? T('token_saved') : '' });
  const user = h('input', { id: 's-user', type: 'text', value: st.user || '' });
  const role = h('select', { id: 's-role' }, h('option', { value: '', text: '' }),
    S.meta.roles.map((r) => h('option', { value: r, text: T('role_' + r), selected: r === st.role })));
  box.appendChild(h('div', { class: 'kv' }, row('teable_url', url), row('token', token), row('user', user), row('role', role)));
  const collect = () => ({ teable_url: url.value.trim(), token: token.value, user: user.value.trim(), role: role.value });
  box.appendChild(h('div', { class: 'toolbar' },
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

  box.appendChild(h('h2', { text: T('project_title') }));
  box.appendChild(h('p', { class: 'muted', text: st.has_project ? T('project_open', { id: st.base_id }) : T('project_none') }));
  const baseId = h('input', { id: 's-base_id', type: 'text' });
  const pname = h('input', { id: 's-project_name', type: 'text' });
  const space = h('input', { id: 's-space_id', type: 'text' });
  box.appendChild(h('div', { class: 'kv' }, row('base_id', baseId), row('project_name', pname), row('space_id', space)));
  const log = h('pre', { id: 'bootstrap-log', class: 'muted' });
  box.appendChild(h('div', { class: 'toolbar' },
    h('button', { class: 'btn primary', type: 'button', id: 'btn-bootstrap', text: T('btn_bootstrap'), onclick: () => guard(async () => {
      const res = await api('/api/bootstrap', { body: { base_id: baseId.value.trim(), project_name: pname.value.trim(), space_id: space.value.trim() } });
      log.textContent = res.log.join('\n');
      toast(T('bootstrap_done', { n: Object.keys(res.table_ids).length }));
      await refreshAll();
    }) })));
  box.appendChild(log);
  if (st.has_project) {
    box.appendChild(h('h2', { text: T('project_settings') }));
    await tableScreen(box, 'cai_dat');
  }
};

SCREENS.tong_quan = async (box) => {
  const data = await api('/api/overview');
  box.appendChild(h('h1', { text: T('nav_tong_quan') }));
  box.appendChild(h('div', { class: 'counters', id: 'counters' }, data.counters.map((c) =>
    h('div', { class: 'counter ' + (c.value ? 'bad' : 'good'), 'data-counter': c.name }, h('b', { text: String(c.value) }), c.text))));
  box.appendChild(h('h2', { text: T('ov_my_leaves') }));
  box.appendChild(data.leaves.length ? h('ul', { class: 'plain', id: 'my-leaves' }, data.leaves.map((l) =>
    h('li', { class: 'click', onclick: () => go('nut', { node: l.code }) }, h('b', { text: l.code }), ' ' + l.name + ' - ', l.next)))
    : h('p', { class: 'muted', text: T('ov_no_leaves') }));
  box.appendChild(h('h2', { text: T('ov_my_warnings') + ' (' + data.warnings.length + ')' }));
  box.appendChild(data.warnings.length ? h('ul', { class: 'plain' }, data.warnings.map((w) =>
    h('li', { class: 'click', onclick: () => go(w.table === 'nut' ? 'cay' : 'nut', { node: w.node || '' }) },
      h('b', { text: w.key || tableLabel(w.table) }), ' (' + tableLabel(w.table) + ') ', w.text)))
    : h('p', { class: 'muted', text: T('ov_none') }));
  box.appendChild(h('p', { class: 'muted', text: T('ov_total_warnings', { n: data.total_warnings }) }));
  box.appendChild(h('h2', { text: T('ov_my_tasks') }));
  box.appendChild(data.tasks.length ? h('ul', { class: 'plain' }, data.tasks.map((t) =>
    h('li', null, h('b', { text: t.key }), ' ' + t.title + (t.due ? ' - ' + t.due : '')))) : h('p', { class: 'muted', text: T('ov_none') }));
};

SCREENS.yeu_cau = async (box) => {
  box.appendChild(h('h1', { text: T('nav_yeu_cau') }));
  await tableScreen(box, 'yeu_cau');
};

SCREENS.kien_truc = async (box) => {
  const data = await api('/api/architectures');
  box.appendChild(h('h1', { text: T('nav_kien_truc') }));
  box.appendChild(h('div', { class: 'toolbar' },
    h('button', { class: 'btn primary', type: 'button', id: 'btn-new-kien_truc', text: T('btn_new'), onclick: () => openForm({ table: 'kien_truc' }) }),
    h('button', { class: 'btn', type: 'button', text: T('btn_csv'), onclick: () => exportCsv('kien_truc') }),
    h('span', { class: 'muted', text: T('arch_weights', { w: data.weights.join(' / ') }) })));
  const cards = h('div', { class: 'cards', id: 'arch-cards' });
  for (const c of data.cards) {
    const f = c.fields;
    const chosen = f.trang_thai === S.meta.values.arch_chosen;
    const dl = h('dl', null,
      ['diem_ky_thuat', 'diem_nguon_hang', 'diem_thoi_gian'].map((k, i) => [h('dt', { text: fieldLabel('kien_truc', k) }), h('dd', { text: num(c.scores[i]) })]),
      h('dt', { text: T('arch_weighted') }), h('dd', { text: c.weighted === null ? '' : String(c.weighted) }),
      h('dt', { text: fieldLabel('kien_truc', 'trang_thai') }), h('dd', { text: num(f.trang_thai) }),
      h('dt', { text: fieldLabel('kien_truc', 'ly_do') }), h('dd', { text: num(f.ly_do) }));
    const card = h('div', { class: 'card' + (chosen ? ' chosen' : '') + (c.draft ? ' draft' : ''), 'data-key': c.key },
      h('h3', { text: c.key + ' - ' + num(f.ten) }),
      c.draft ? h('span', { class: 'badge draft', text: T('draft_mark') }) : null,
      h('p', { class: 'muted', text: num(f.nguyen_ly) }), dl,
      c.warnings.map((w) => h('div', { class: 'err', text: w })),
      h('div', { class: 'toolbar' },
        h('button', { class: 'btn', type: 'button', text: T('btn_edit'), onclick: () => openRow('kien_truc', c.key) }),
        h('button', { class: 'btn primary', type: 'button', 'data-choose': c.key, disabled: !data.can_choose || chosen,
          title: data.can_choose ? '' : T('role_needed'), text: T('btn_choose'), onclick: () => chooseArchitecture(c) })));
    cards.appendChild(card);
  }
  box.appendChild(cards);
  if (!data.cards.length) box.appendChild(h('p', { class: 'muted', text: T('empty') }));
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
          base_modified: card.modified, base_fields: card.fields, draft_id: card.draft || undefined,
          fields: { trang_thai: S.meta.values.arch_chosen, ly_do: reason.value.trim() } } });
      } catch (e) { showError(e); return; }
      closeModal();
      toast(T('draft_saved'));
      await refreshAll();
    } }),
  ]);
}

SCREENS.cay = async (box) => {
  const data = await api('/api/tree_nodes');
  box.appendChild(h('h1', { text: T('nav_cay') }));
  const bar = h('div', { class: 'toolbar' });
  for (const key of Object.keys(data.gates)) {
    const cb = h('input', { type: 'checkbox', id: 'gate-' + key, disabled: !data.can_gate, checked: data.gates[key] || false,
      title: data.can_gate ? '' : T('role_needed') });
    cb.addEventListener('change', () => setGate(key, cb.checked, cb));
    bar.appendChild(h('label', { class: 'switch' }, cb, T('gate_' + key)));
  }
  bar.appendChild(h('button', { class: 'btn primary', type: 'button', id: 'btn-new-nut', text: T('btn_new'), onclick: () => openForm({ table: 'nut' }) }));
  bar.appendChild(h('button', { class: 'btn', type: 'button', text: T('btn_csv'), onclick: () => exportCsv('nut') }));
  box.appendChild(bar);
  const t = h('table', { class: 'grid', id: 'node-tree' });
  t.appendChild(h('thead', null, h('tr', null, ['', T('col_node'), T('col_level'), T('col_owner'), T('col_next'), T('col_cost'), ''].map((x) => h('th', { class: 'nosort', text: x })))));
  const body = h('tbody');
  for (const n of data.nodes) {
    const tr = h('tr', { class: 'indent-row' + (n.draft ? ' is-draft' : ''), 'data-node': n.code, onclick: () => selectNode(n.code) },
      h('td', null, n.draft ? h('span', { class: 'badge draft', text: T('draft_mark') }) : null,
        n.warnings.length ? h('span', { class: 'badge warn', title: n.warnings.join('\n'), text: '! ' + n.warnings.length }) : null),
      h('td', { style: 'padding-left:' + (8 + n.depth * 20) + 'px' }, h('b', { text: n.code }), ' ' + n.name),
      h('td', { text: String(n.level) }), h('td', { text: n.owner }), h('td', { text: n.next }), h('td', { class: 'num', text: String(n.cost) }),
      h('td', null,
        h('button', { class: 'btn', type: 'button', text: T('btn_edit'), onclick: (ev) => { ev.stopPropagation(); openRow('nut', n.code); } }),
        n.level < 2 ? h('button', { class: 'btn', type: 'button', 'data-add-child': n.code, text: T('btn_add_child'),
          onclick: (ev) => { ev.stopPropagation(); openForm({ table: 'nut', prefill: { ma_cha: n.code } }); } }) : null,
        n.leaf ? h('button', { class: 'btn', type: 'button', text: T('btn_open_node'), onclick: (ev) => { ev.stopPropagation(); go('nut', { node: n.code }); } }) : null));
    body.appendChild(tr);
  }
  t.appendChild(body);
  box.appendChild(h('div', { class: 'tablewrap' }, t));
  if (!data.nodes.length) box.appendChild(h('p', { class: 'muted', text: T('empty') }));
};

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

SCREENS.phan_bo = async (box) => {
  const data = await api('/api/alloc');
  box.appendChild(h('h1', { text: T('nav_phan_bo') }));
  box.appendChild(h('div', { class: 'toolbar' },
    h('button', { class: 'btn primary', type: 'button', id: 'btn-new-phan_bo', text: T('btn_new'), onclick: () => openForm({ table: 'phan_bo' }) }),
    h('button', { class: 'btn', type: 'button', text: T('btn_csv'), onclick: () => exportCsv('phan_bo') })));
  const t = h('table', { class: 'grid', id: 'alloc-matrix' });
  t.appendChild(h('thead', null, h('tr', null,
    h('th', { class: 'nosort', text: T('col_requirement') }),
    data.nodes.map((n) => h('th', { class: 'nosort', title: withName('nut', n), text: withName('nut', n) })),
    h('th', { class: 'nosort', text: T('col_budget_total') }), h('th', { class: 'nosort', text: T('col_margin') }))));
  const body = h('tbody');
  for (const r of data.requirements) {
    const b = data.budgets[r.code];
    const tr = h('tr', { 'data-req': r.code }, h('td', { title: r.text }, h('b', { text: r.code }), ' ' + r.text.slice(0, 28)));
    for (const n of data.nodes) {
      const cell = data.cells[r.code + '|' + n];
      const td = h('td', { class: 'cell' + (cell && cell.draft ? ' over' : ''), 'data-cell': r.code + '|' + n,
        title: cell ? cell.key + ' ' + cell.kieu : T('alloc_create'),
        onclick: () => (cell ? openRow('phan_bo', cell.key) : openForm({ table: 'phan_bo', prefill: { ma_yc: r.code, ma_nut: n } })) });
      td.textContent = cell ? (cell.value !== null && cell.value !== undefined ? String(cell.value) : '•') : '';
      tr.appendChild(td);
    }
    tr.appendChild(h('td', { class: 'num' + (b && b.over ? ' fail' : ''), text: b ? String(b.total) : '' }));
    tr.appendChild(h('td', { class: 'num' + (b && b.over ? ' fail' : ''), text: b && b.margin !== null ? String(b.margin) : '' }));
    body.appendChild(tr);
  }
  t.appendChild(body);
  box.appendChild(h('div', { class: 'tablewrap' }, t));
  if (!data.requirements.length) box.appendChild(h('p', { class: 'muted', text: T('empty') }));
};

SCREENS.nut = async (box) => {
  const data = await api('/api/node', { query: { code: S.node } });
  box.appendChild(h('h1', { text: T('nav_nut') }));
  if (!data.node) {
    box.appendChild(h('p', { class: 'muted', text: T('node_pick') }));
    box.appendChild(h('ul', { class: 'plain', id: 'leaf-list' }, data.leaves.map((l) =>
      h('li', { class: 'click', onclick: () => selectNode(l.code) }, h('b', { text: l.code }), ' ' + l.name + (l.owner ? ' - ' + l.owner : '')))));
    return;
  }
  const n = data.node;
  box.appendChild(h('div', { class: 'toolbar' },
    h('button', { class: 'btn', type: 'button', text: T('node_back'), onclick: () => selectNode('') }),
    h('b', { text: n.ma_nut + ' ' + (n.ten || '') }), h('span', { class: 'muted', text: (n.phu_trach || T('none')) + ' - ' + n.next })));
  if (!n.leaf) box.appendChild(h('p', { class: 'muted', text: T('node_not_leaf') }));

  const section = (title, addTable, prefill, el) => {
    box.appendChild(h('h2', { text: title }));
    if (addTable && n.leaf) box.appendChild(h('div', { class: 'toolbar' }, h('button', { class: 'btn', type: 'button', 'data-add': addTable, text: T('btn_new') + ' ' + tableLabel(addTable),
      onclick: () => openForm({ table: addTable, prefill }) })));
    box.appendChild(el);
  };
  const simple = (table, rows, cols, extra) => {
    const t = h('table', { class: 'grid', 'data-table': table });
    t.appendChild(h('thead', null, h('tr', null, h('th', { class: 'nosort' }), cols.map((c) => h('th', { class: 'nosort', text: fieldLabel(table, c) })), extra ? h('th', { class: 'nosort', text: extra.label }) : null)));
    t.appendChild(h('tbody', null, rows.map((r) => {
      const idName = specOf(table).id_field;
      return h('tr', { class: r._draft ? 'is-draft' : '', 'data-key': r[idName] || r._key, onclick: () => openRow(table, r[idName] || r._key) },
        h('td', null, r._draft ? h('span', { class: 'badge draft', text: T('draft_mark') }) : null,
          (r._warnings && r._warnings.length) ? h('span', { class: 'badge warn', title: r._warnings.join('\n'), text: '! ' + r._warnings.length }) : null),
        cols.map((c) => h('td', { text: ((specOf(table).fields[c] || {}).ref ? cellText(table, c, r[c]) : num(r[c])) })), extra ? h('td', { text: extra.get(r) }) : null);
    })));
    return h('div', { class: 'tablewrap' }, t);
  };
  section(T('node_alloc'), 'phan_bo', { ma_nut: n.ma_nut }, simple('phan_bo', data.allocations, ['ma_pb', 'ma_yc', 'kieu', 'gia_tri_phan_bo', 'don_vi']));
  section(T('node_specs'), 'thong_so', { ma_nut: n.ma_nut }, simple('thong_so', data.specs, ['ma_ts', 'ma_yc_goc', 'thong_so', 'gia_tri_min', 'gia_tri_max', 'don_vi', 'muc']));
  section(T('node_cands'), 'ung_vien', { ma_nut: n.ma_nut }, simple('ung_vien', data.candidates, ['ma_uv', 'hang', 'model', 'gia_cong_bo', 'tien_te', 'trang_thai'], { label: T('extra_result'), get: (r) => r._result }));

  const cmp = data.compare;
  box.appendChild(h('h2', { text: T('node_compare') }));
  if (!cmp.candidates.length || !cmp.rows.length) {
    box.appendChild(h('p', { class: 'muted', text: T('node_compare_empty') }));
    return;
  }
  const ct = h('table', { class: 'grid', id: 'compare' });
  ct.appendChild(h('thead', null, h('tr', null, h('th', { class: 'nosort', text: T('col_spec') }),
    cmp.candidates.map((uv) => h('th', { class: 'nosort' }, uv, h('div', { class: cmp.pass[uv] ? 'pass' : 'unchecked', text: cmp.results[uv] }))))));
  ct.appendChild(h('tbody', null, cmp.rows.map((r) => h('tr', { 'data-spec': r.ts },
    h('td', null, h('b', { text: r.ts }), ' ' + r.name, h('div', { class: 'muted', text: [r.min, r.max].map(num).join(' ... ') + ' ' + r.unit + ' (' + r.muc + ')' })),
    r.cells.map((c) => h('td', { class: 'cell', 'data-cell': c.uv + '|' + r.ts, title: [c.quote, c.page].filter(Boolean).join(' / '),
      onclick: () => editCheck(c.uv, r.ts, n.ma_nut) },
      h('span', { class: c.state === 'pass' ? 'pass' : (c.state === 'fail' ? 'fail' : 'unchecked'), text: c.state === 'unchecked' ? '?' : num(c.value) || T('state_' + c.state) }),
      c.draft ? h('span', { class: 'badge draft', text: T('draft_mark') }) : null))))));
  box.appendChild(h('div', { class: 'tablewrap' }, ct));
};

async function editCheck(uv, ts, node) {
  const key = uv + '|' + ts;
  const data = await getRows('doi_chieu', { node });
  const row = data.rows.find((r) => r.key === key);
  if (row) openForm({ table: 'doi_chieu', row });
  else openForm({ table: 'doi_chieu', prefill: { ma_uv: uv, ma_ts: ts, khoa: key } });
}

SCREENS.mua_hang = async (box) => {
  const q = await api('/api/sourcing');
  box.appendChild(h('h1', { text: T('nav_mua_hang') }));
  box.appendChild(h('h2', { text: T('src_queue') + ' (' + q.queue.length + ')' }));
  box.appendChild(q.queue.length ? h('ul', { class: 'plain', id: 'src-queue' }, q.queue.map((c) =>
    h('li', { class: 'click', 'data-uv': c.uv, onclick: () => openForm({ table: 'mua_hang', prefill: { ma_uv: c.uv, tien_te: c.currency } }) },
      h('b', { text: c.uv }), ' ' + withName('nut', c.node) + ' - ' + [c.hang, c.model].filter(Boolean).join(' ') + (c.price !== null && c.price !== undefined ? ' - ' + c.price + ' ' + c.currency : ''))))
    : h('p', { class: 'muted', text: T('src_queue_empty') }));
  box.appendChild(h('h2', { text: T('src_rows') }));
  await tableScreen(box, 'mua_hang');
};

SCREENS.rfq = async (box) => {
  box.appendChild(h('h1', { text: T('nav_rfq') }));
  const data = await getRows('rfq');
  const states = [...new Set(data.rows.map((r) => r.fields.trang_thai || ''))];
  const bar = h('div', { class: 'toolbar' });
  const sel = h('select', { id: 'rfq-status' }, h('option', { value: '', text: T('rfq_all_status') }), states.map((s) => h('option', { value: s, text: s || T('none') })));
  bar.appendChild(h('button', { class: 'btn primary', type: 'button', id: 'btn-new-rfq', text: T('btn_new'), onclick: () => openForm({ table: 'rfq' }) }));
  bar.appendChild(sel);
  bar.appendChild(h('button', { class: 'btn', type: 'button', text: T('btn_csv'), onclick: () => exportCsv('rfq') }));
  box.appendChild(bar);
  const holder = h('div');
  const draw = () => {
    holder.textContent = '';
    const rows = data.rows.filter((r) => !sel.value || (r.fields.trang_thai || '') === sel.value);
    holder.appendChild(tableView('rfq', Object.assign({}, data, { rows }), { link: 'link_tai_lieu' }));
  };
  sel.addEventListener('change', draw);
  draw();
  box.appendChild(holder);
};

SCREENS.moc = async (box) => {
  box.appendChild(h('h1', { text: T('nav_moc') }));
  box.appendChild(h('h2', { text: tableLabel('moc') }));
  await tableScreen(box, 'moc');
  box.appendChild(h('h2', { text: tableLabel('quyet_dinh') }));
  await tableScreen(box, 'quyet_dinh');
};

SCREENS.commit = async (box) => {
  const data = await api('/api/drafts');
  const st = S.st || (await loadState());
  box.appendChild(h('h1', { text: T('nav_commit') }));
  const results = h('div', { id: 'commit-results' });
  const btn = h('button', { class: 'btn primary', type: 'button', id: 'btn-commit', text: T('btn_commit'),
    disabled: !st.can_commit || !data.drafts.length, title: st.can_commit ? '' : T('commit_disabled'),
    onclick: () => runCommit(results) });
  box.appendChild(h('div', { class: 'toolbar' }, btn, st.can_commit ? null : h('span', { class: 'err', text: T('commit_disabled') })));
  if (!data.drafts.length) box.appendChild(h('p', { class: 'muted', text: T('drafts_empty') }));
  else {
    const t = h('table', { class: 'grid', id: 'draft-list' });
    t.appendChild(h('thead', null, h('tr', null, [T('col_table'), T('col_key'), T('col_op'), T('col_state'), ''].map((x) => h('th', { class: 'nosort', text: x })))));
    t.appendChild(h('tbody', null, data.drafts.map((d) => h('tr', { 'data-draft': d.id, onclick: () => openRow(d.table, d.key) },
      h('td', { text: tableLabel(d.table) }), h('td', { text: d.key }), h('td', { text: T('op_' + d.op) }),
      h('td', { class: d.valid ? 'ok' : 'err', text: d.valid ? T('valid') : d.issues.map((i) => fieldLabel(d.table, i.field) + ': ' + i.message).join('; ') }),
      h('td', null, h('button', { class: 'btn', type: 'button', 'data-discard': d.id, text: T('btn_discard'), onclick: (ev) => { ev.stopPropagation(); discardDraft(d); } }))))));
    box.appendChild(h('div', { class: 'tablewrap' }, t));
  }
  box.appendChild(results);
};

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
    if (r.status === 'conflict' && r.conflict) li.appendChild(h('button', { class: 'btn', type: 'button', 'data-resolve': r.draft_id, text: T('btn_resolve'), onclick: () => conflictDialog(r) }));
    if (r.status === 'stale' && r.stale) li.appendChild(h('button', { class: 'btn', type: 'button', 'data-resolve': r.draft_id, text: T('btn_resolve'), onclick: () => staleDialog(r) }));
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
  const t = h('table', { class: 'grid' }, h('thead', null, h('tr', null, [T('col_field'), T('stale_base'), T('stale_mine'), T('stale_theirs')].map((x) => h('th', { class: 'nosort', text: x })))), h('tbody', null, rows));
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

/* ---------- keyboard ---------- */

document.addEventListener('keydown', (ev) => {
  const mod = ev.ctrlKey || ev.metaKey;
  if (ev.key === 'F1') { ev.preventDefault(); widenPanel(); return; }
  if (mod && (ev.key === 's' || ev.key === 'S')) {
    ev.preventDefault();
    if (S.form) S.form.save();
    return;
  }
  if (mod && ev.key === 'Enter') { ev.preventDefault(); closeModal(); go('commit'); return; }
  if (ev.key === 'Escape' && S.form) closeModal();
});

/* ---------- start ---------- */

async function start() {
  try {
    S.meta = await api('/api/meta');
  } catch (e) {
    document.getElementById('main').textContent = String((e.err && e.err.detail) || e);
    return;
  }
  for (const el of document.querySelectorAll('[data-i]')) el.textContent = T(el.dataset.i);
  for (const el of document.querySelectorAll('[data-i-title]')) el.title = T(el.dataset.iTitle);
  document.getElementById('panel-toggle').addEventListener('click', () => setPanel(S.panel === 'strip' ? 'open' : 'strip'));
  document.getElementById('panel-wide').addEventListener('click', widenPanel);
  document.getElementById('panel-strip').addEventListener('click', () => setPanel('open'));
  let saved = 'open';
  try { saved = localStorage.getItem('t3_panel') || 'open'; } catch (e) { /* no storage: keep the default */ }
  setPanel(saved === 'strip' ? 'strip' : 'open');
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
