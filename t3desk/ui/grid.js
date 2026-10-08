'use strict';
/* Inline-edit grid (docs/UI-V2-SPEC.md section 3). Replaces the "add" pop-up form.
 *
 * One grid shows one table. Every column comes from schema.yaml, nothing is named here.
 * A cell edit becomes a draft at once (same /api/draft calls as before):
 *   - a committed row sends only the changed fields with its base_modified, so the stale check still works;
 *   - a new row is re-saved whole with its draft_id; a half-filled new row is kept as a draft with its issues
 *     (partial: true) and blocks Commit until every issue is fixed.
 * The keys are handled in keys.js, which calls the methods of Grid.current. The grid itself only listens
 * for mouse clicks and for the keys of its open editor (menu up/down, Enter on a highlighted option). */

const Grid = { current: null };

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** The reason an issue gives, in Vietnamese; the server's English message is kept as a hint after it. */
function issueText(i) {
  const known = S.meta.labels.ui['v_' + i.code] !== undefined;
  return known ? T('v_' + i.code) : i.message;
}

function gridCompositeId(spec, fields) {
  const parts = spec.id.parts.map((p) => fields[p]);
  return parts.every((p) => p !== undefined && p !== null && p !== '') ? parts.join(spec.id.separator) : '';
}

/** The text shown in a cell: a code is never shown alone when its name is known. */
function gridCell(table, name, fs, value) {
  if (value === null || value === undefined || value === '') return h('span', { class: 'empty' });
  if (fs && fs.ref) {
    const sep = fs.multi || null;
    const codes = sep ? String(value).split(sep).map((c) => c.trim()).filter(Boolean) : [String(value)];
    if (sep) return h('span', { class: 'chips' }, codes.map((c) => h('span', { class: 'chip', title: withName(fs.ref, c), text: c })));
    const nm = ((S.names || {})[fs.ref] || {})[codes[0]];
    return h('span', null, codes[0], nm ? h('i', { class: 'nm', text: ' - ' + nm }) : null);
  }
  if (table === 'cai_dat' && name === 'khoa' && settingLabel(value)) return h('span', null, settingLabel(value), h('i', { class: 'nm', text: ' (' + value + ')' }));
  return h('span', { text: String(value) });
}

function buildGrid(table, data, o) {
  const opts = o || {};
  const spec = specOf(table);
  const idName = spec.id_field;
  const kind = spec.id.kind;
  const names = Object.keys(spec.fields);
  const g = {
    table, spec, rows: data.rows, cur: { r: 0, c: 0 }, edit: null, menu: null, pending: {}, proposed: '',
    host: h('div', { class: 'grid-host', tabindex: '0', 'data-table': table, role: 'grid', 'aria-label': tableLabel(table) }),
    msg: h('div', { class: 'grid-msg', role: 'status' }),
  };
  const extras = [...new Set(g.rows.flatMap((r) => Object.keys(r.extras || {})))];
  const dead = () => !g.host.isConnected;

  /* ---------- model helpers ---------- */

  const nameOfCol = (c) => (c < names.length ? names[c] : null);
  const colCount = () => names.length;
  const sorted = () => sortRows(table, g.rows);
  g.view = sorted();
  const rowCount = () => g.view.length;
  const isNewRow = (r) => r === rowCount();
  const rowAt = (r) => g.view[r] || null;

  function readonly(r, c) {
    const name = nameOfCol(c);
    if (!name) return true;
    const placed = rowAt(r);
    if (placed && placed.effective && placed.effective[name] !== undefined) return true; // supplied by the library item
    if (name === idName) {
      if (kind === 'composite') return true; // built from its parts
      const row = rowAt(r);
      return !!row && row.draft_op !== 'create'; // an ID cannot be edited after commit
    }
    return false;
  }

  function cellValue(r, c) {
    const name = nameOfCol(c);
    const row = rowAt(r);
    if (row) return row.fields[name];
    if (name === idName && kind === 'number') return undefined;
    return g.pending[name] !== undefined ? g.pending[name] : (opts.prefill || {})[name];
  }

  const issuesOf = (row) => (row ? (row.issues || []) : []);

  /* ---------- drawing ---------- */

  function headerCell(name) {
    const fs = spec.fields[name];
    const dir = S.sort[table] && S.sort[table].col === name && !S.sort[table].extra ? (S.sort[table].dir > 0 ? ' ▲' : ' ▼') : '';
    return h('th', { scope: 'col', title: fs && fs.help ? fs.help : '', onclick: () => {
      const cur = S.sort[table];
      S.sort[table] = { col: name, extra: false, dir: cur && cur.col === name ? -cur.dir : 1 };
      g.view = sorted();
      draw();
    } }, fieldLabel(table, name) + (fs && fs.required ? ' *' : '') + dir);
  }

  function draw() {
    const tbl = h('table', { class: 'grid inline', 'data-table': table });
    tbl.appendChild(h('thead', null, h('tr', null, h('th', { class: 'rn' }), opts.actions ? h('th', { class: 'ro act' }) : null, names.map(headerCell),
      extras.map((x) => h('th', { class: 'ro', text: T('extra_' + x) })))));
    const body = h('tbody');
    g.view.forEach((row, r) => {
      const issues = issuesOf(row);
      const tr = h('tr', { 'data-key': row.key, class: row.draft ? 'is-draft' : '' });
      const rn = h('td', { class: 'rn' }, String(r + 1), row.draft ? h('span', { class: 'mark', title: T('draft_mark'), text: ' ✎' }) : null,
        row.warnings && row.warnings.length ? h('span', { class: 'badge warn', title: row.warnings.join('\n'), text: '! ' + row.warnings.length }) : null,
        row.notes ? h('span', { class: 'badge note', title: T('notes_title', { key: withName(table, row.key) }), text: '✉ ' + row.notes }) : null);
      tr.appendChild(rn);
      if (opts.actions) tr.appendChild(h('td', { class: 'act' }, opts.actions(row) || null)); // right after the row number: always in view
      names.forEach((name, c) => {
        const bad = issues.filter((i) => i.field === name);
        const td = h('td', { 'data-col': name, class: 'cell' + (readonly(r, c) ? ' ro' : '') + (bad.length ? ' err' : ''),
          title: bad.map((i) => T('v_' + i.code) + ' - ' + i.message).join('\n') });
        const fromLibrary = row.effective && row.effective[name] !== undefined;
        td.appendChild(gridCell(table, name, spec.fields[name], fromLibrary ? row.effective[name] : row.fields[name]));
        if (fromLibrary) td.title = T('grid_from_library');
        td.addEventListener('mousedown', () => { g.select(r, c); });
        td.addEventListener('dblclick', () => g.startEdit(null));
        tr.appendChild(td);
      });
      extras.forEach((x) => tr.appendChild(h('td', { class: 'cell ro extra', text: String(num((row.extras || {})[x])) })));
      body.appendChild(tr);
    });
    if (!opts.noNew) {
      const r = rowCount();
      const tr = h('tr', { class: 'new-row', 'data-new': '1' }, h('td', { class: 'rn', text: '＊' }), opts.actions ? h('td', { class: 'act' }) : null);
      names.forEach((name, c) => {
        const td = h('td', { 'data-col': name, class: 'cell new' + (readonly(r, c) ? ' ro' : '') });
        const v = cellValue(r, c);
        if (name === idName && kind === 'number') td.appendChild(h('span', { class: 'ghost', text: (g.proposed || '') + ' ' + T('grid_auto_id') }));
        else if (v !== undefined && v !== '') td.appendChild(gridCell(table, name, spec.fields[name], v));
        td.addEventListener('mousedown', () => { g.select(r, c); });
        td.addEventListener('dblclick', () => g.startEdit(null));
        tr.appendChild(td);
      });
      extras.forEach(() => tr.appendChild(h('td', { class: 'cell ro extra' })));
      body.appendChild(tr);
    }
    tbl.appendChild(body);
    g.host.textContent = '';
    g.host.appendChild(tbl);
    if (!g.view.length) g.host.appendChild(h('p', { class: 'muted pad', text: T('empty') }));
    g.tbl = tbl;
    paintCursor();
    paintMessages();
  }

  function paintMessages() {
    const all = [];
    for (const row of g.view) for (const i of issuesOf(row)) all.push(withName(table, row.key) + ': ' + fieldLabel(table, i.field) + ' - ' + issueText(i));
    g.msg.textContent = '';
    if (all.length) {
      g.msg.appendChild(h('span', { class: 'badge warn', text: T('grid_issues', { n: all.length }) }));
      g.msg.appendChild(h('span', { class: 'err', text: ' ' + all[0] + (all.length > 1 ? ' (+' + (all.length - 1) + ')' : '') }));
    }
  }

  function cellEl(r, c) {
    const tr = g.tbl && g.tbl.tBodies[0].rows[r];
    return tr ? tr.cells[c + (opts.actions ? 2 : 1)] : null;
  }

  function paintCursor() {
    for (const el of g.host.querySelectorAll('td.sel')) el.classList.remove('sel');
    const el = cellEl(g.cur.r, g.cur.c);
    if (el) {
      el.classList.add('sel');
      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
    const tr = el ? el.parentElement : null;
    for (const x of g.host.querySelectorAll('tr.cur')) x.classList.remove('cur');
    if (tr) tr.classList.add('cur');
  }

  /* ---------- cursor ---------- */

  g.select = (r, c) => {
    const maxR = opts.noNew ? rowCount() - 1 : rowCount();
    g.cur = { r: Math.max(0, Math.min(r, Math.max(maxR, 0))), c: Math.max(0, Math.min(c, colCount() - 1)) };
    Grid.current = g;
    paintCursor();
    const row = rowAt(g.cur.r);
    if (opts.onSelect) opts.onSelect(row);
    if (document.activeElement !== g.host && !g.edit) g.host.focus({ preventScroll: true });
  };

  g.move = (dr, dc) => g.select(g.cur.r + dr, g.cur.c + dc);
  g.isEditing = () => !!g.edit;
  g.hasMenu = () => !!g.menu;
  g.focus = () => { Grid.current = g; g.host.focus({ preventScroll: true }); };

  /* ---------- editor ---------- */

  async function optionsFor(name, fs) {
    if (fs.type === 'choice') return fs.choices.map((v) => ({ value: v, text: v }));
    if (fs.ref) {
      const ids = await idChoices(fs.ref);
      const extra = (fs.ref_extra || []).map((v) => ({ value: v, text: v }));
      return ids.map((id) => ({ value: id, text: withName(fs.ref, id) })).concat(extra);
    }
    return null;
  }

  function closeEditor() {
    if (g.menu) { g.menu.remove(); g.menu = null; }
    g.edit = null;
    const el = cellEl(g.cur.r, g.cur.c);
    if (el) el.classList.remove('editing');
  }

  function showMenu(input, options) {
    if (g.menu) g.menu.remove();
    const rect = input.getBoundingClientRect();
    const menu = h('div', { class: 'dd', role: 'listbox', style: 'left:' + rect.left + 'px;top:' + (rect.bottom + 1) + 'px;min-width:' + Math.max(rect.width, 220) + 'px' });
    document.body.appendChild(menu);
    g.menu = menu;
    menu._options = options;
    menu._at = 0;
    return menu;
  }

  function filterMenu(input, fs, options) {
    const multi = fs.multi || null;
    const typed = (multi ? input.value.split(multi).pop() : input.value).trim().toLowerCase();
    const shown = options.filter((op) => !typed || op.text.toLowerCase().includes(typed) || op.value.toLowerCase().includes(typed)).slice(0, 60);
    const menu = g.menu || showMenu(input, options);
    menu.textContent = '';
    menu._shown = shown;
    menu._at = Math.min(menu._at, Math.max(shown.length - 1, 0));
    shown.forEach((op, i) => menu.appendChild(h('div', { role: 'option', class: i === menu._at ? 'hl' : '', 'aria-selected': String(i === menu._at),
      onmousedown: (ev) => { ev.preventDefault(); pick(input, fs, op); } }, op.text)));
    if (!shown.length) menu.appendChild(h('div', { class: 'muted', text: T('grid_no_match') }));
  }

  function pick(input, fs, op) {
    if (fs.multi) {
      const parts = input.value.split(fs.multi).map((p) => p.trim()).filter(Boolean);
      parts.pop();
      if (!parts.includes(op.value)) parts.push(op.value);
      input.value = parts.join(fs.multi);
      if (g.menu) { g.menu.remove(); g.menu = null; }
      return;
    }
    input.value = op.value;
    if (g.menu) { g.menu.remove(); g.menu = null; }
    g.commit('down');
  }

  g.startEdit = async (initial) => {
    if (g.edit) return;
    const { r, c } = g.cur;
    const name = nameOfCol(c);
    if (!name) return;
    if (readonly(r, c)) { toast(T('grid_readonly')); return; }
    const fs = spec.fields[name];
    const cell = cellEl(r, c);
    if (!cell) return;
    const current = cellValue(r, c);
    const input = h('input', { class: 'cell-input', type: 'text', 'aria-label': fieldLabel(table, name), autocomplete: 'off' });
    input.value = initial !== null && initial !== undefined ? initial : (current === undefined || current === null ? '' : String(current));
    const options = await optionsFor(name, fs);
    if (g.edit || dead()) return;
    cell.classList.add('editing');
    cell.textContent = '';
    cell.appendChild(input);
    g.edit = { r, c, name, fs, input, options };
    input.focus();
    if (initial === null) input.select();
    if (options) filterMenu(input, fs, options);
    input.addEventListener('input', () => { if (options) { if (g.menu) g.menu._at = 0; filterMenu(input, fs, options); } });
    input.addEventListener('keydown', (ev) => editorKey(ev, input, fs, options));
    input.addEventListener('blur', () => { setTimeout(() => { if (g.edit && g.edit.input === input && document.activeElement !== input && !(g.menu && g.menu.contains(document.activeElement))) g.commit('none'); }, 120); });
  };

  /** Keys that only make sense inside an open editor with a menu. Everything else goes on to keys.js. */
  function editorKey(ev, input, fs, options) {
    const menu = g.menu;
    if (menu && (ev.key === 'ArrowDown' || ev.key === 'ArrowUp')) {
      ev.preventDefault();
      ev.stopPropagation();
      menu._at = Math.max(0, Math.min((menu._shown || []).length - 1, menu._at + (ev.key === 'ArrowDown' ? 1 : -1)));
      filterMenu(input, fs, options);
      return;
    }
    if (menu && (ev.key === 'Enter' || ev.key === 'Tab') && !ev.shiftKey) {
      const shown = menu._shown || [];
      const exact = options.some((op) => op.value === input.value.trim());
      if (shown.length && !exact) {
        ev.preventDefault();
        ev.stopPropagation();
        const op = shown[menu._at];
        if (fs.multi) { pick(input, fs, op); return; }
        input.value = op.value;
        g.commit(ev.key === 'Tab' ? 'right' : 'down');
      }
    }
  }

  function parse(fs, raw) {
    const v = raw.trim();
    if (v === '') return { value: '' };
    if (fs.type === 'number') {
      const n = Number(v.replace(',', '.'));
      return Number.isFinite(n) ? { value: n } : { error: T('v_type') };
    }
    if (fs.type === 'date') return DATE_RE.test(v) ? { value: v } : { error: T('grid_date') };
    if (fs.type === 'choice') return fs.choices.includes(v) ? { value: v } : { error: T('v_not_allowed') };
    if (fs.multi) return { value: v.split(fs.multi).map((p) => p.trim()).filter(Boolean).join(fs.multi) };
    return { value: v };
  }

  g.cancel = () => {
    closeEditor();
    draw();
    g.host.focus({ preventScroll: true });
  };

  g.commit = async (dir) => {
    if (!g.edit) { moveAfter(dir); return; }
    const { r, c, name, fs, input } = g.edit;
    const res = parse(fs, input.value);
    if (res.error) {
      g.msg.textContent = '';
      g.msg.appendChild(h('span', { class: 'err', text: fieldLabel(table, name) + ': ' + res.error }));
      input.classList.add('bad');
      input.focus();
      return;
    }
    const before = cellValue(r, c);
    closeEditor();
    const same = String(before === undefined || before === null ? '' : before) === String(res.value);
    if (!same || isNewRow(r)) {
      try { await saveCell(r, name, res.value); } catch (e) { showError(e); }
    }
    draw();
    moveAfter(dir);
  };

  function moveAfter(dir) {
    if (dir === 'down') g.move(1, 0);
    else if (dir === 'up') g.move(-1, 0);
    else if (dir === 'right') { if (g.cur.c + 1 >= colCount()) g.select(g.cur.r + 1, 0); else g.move(0, 1); }
    else if (dir === 'left') { if (g.cur.c === 0) g.select(g.cur.r - 1, colCount() - 1); else g.move(0, -1); }
    else g.select(g.cur.r, g.cur.c);
    g.host.focus({ preventScroll: true });
  }

  /* ---------- saving ---------- */

  async function proposeId() {
    if (kind !== 'number') { g.proposed = ''; return; }
    const q = { table };
    const parent = (opts.prefill || {}).ma_cha;
    if (parent) q.parent = parent;
    try { g.proposed = (await api('/api/next_id', { query: q })).id || ''; } catch (e) { g.proposed = ''; }
  }

  const changedFields = (row) => {
    const out = {};
    for (const k of Object.keys(row.fields)) {
      if (k === idName) continue;
      const a = row.fields[k] === '' ? null : row.fields[k];
      const b = row.base && row.base[k] !== undefined ? row.base[k] : null;
      if (String(a) !== String(b)) out[k] = row.fields[k];
    }
    return out;
  };

  async function saveCell(r, name, value) {
    let body;
    const row = rowAt(r);
    if (row && row.draft_op === 'create') {
      const fields = { ...row.fields };
      if (value === '') delete fields[name]; else fields[name] = value;
      if (kind === 'composite') { const id = gridCompositeId(spec, fields); if (id) fields[idName] = id; }
      body = { table, op: 'create', fields, draft_id: row.draft, partial: true };
    } else if (row) {
      const changes = changedFields(row);
      const base = row.base && row.base[name] !== undefined ? row.base[name] : null;
      if (String(value === '' ? null : value) === String(base)) delete changes[name]; else changes[name] = value;
      if (!Object.keys(changes).length && row.draft) {
        await api('/api/draft/discard', { body: { draft_id: row.draft } });
        await g.reload();
        return;
      }
      body = { table, op: 'update', key: row.key, record_id: row.record_id, base_modified: row.modified, base_fields: row.base || row.fields,
        draft_id: row.draft || undefined, fields: changes, partial: true };
    } else {
      // the new row at the bottom: keep the typed values until its ID is known, then save it as a draft
      if (value === '') delete g.pending[name]; else g.pending[name] = value;
      const fields = { ...(opts.prefill || {}), ...g.pending };
      if (kind === 'number') { if (!g.proposed) await proposeId(); fields[idName] = g.proposed; }
      else if (kind === 'composite') { const id = gridCompositeId(spec, fields); if (id) fields[idName] = id; }
      if (!fields[idName]) return; // the ID is not known yet: stays on screen, not yet a draft
      body = { table, op: 'create', fields, partial: true };
    }
    await api('/api/draft', { body });
    delete S.tableCache[table];
    if (!row) { g.pending = {}; g.justCreated = body.fields[idName]; await proposeId(); }
    await g.reload();
    await loadState();
    if (opts.onChange) opts.onChange(table);
  }

  g.reload = async () => {
    const keep = rowAt(g.cur.r) ? rowAt(g.cur.r).key : (g.justCreated || null);
    const fresh = await opts.fetch();
    g.rows = fresh.rows;
    g.view = sorted();
    if (fresh.names) S.names = Object.assign({}, S.names, fresh.names);
    if (keep) { const at = g.view.findIndex((x) => x.key === keep); if (at >= 0) g.cur.r = at; }
    g.justCreated = null;
    draw();
  };

  /* ---------- row operations (called from keys.js) ---------- */

  g.copyAbove = async () => {
    const { r, c } = g.cur;
    if (r === 0 || readonly(r, c)) return;
    const name = nameOfCol(c);
    const above = rowAt(r - 1);
    if (!above) return;
    try { await saveCell(r, name, above.fields[name] === undefined ? '' : above.fields[name]); } catch (e) { showError(e); }
    draw();
  };

  g.newRow = async () => {
    await proposeId();
    const first = names.findIndex((n, c) => !readonly(rowCount(), c) && !(n === idName && kind === 'number'));
    g.select(rowCount(), Math.max(first, 0));
    draw();
    g.startEdit(null);
  };

  g.discardRow = async () => {
    const row = rowAt(g.cur.r);
    if (!row || !row.draft) return;
    if (!window.confirm(T('confirm_discard', { key: row.key }))) return;
    await guard(async () => {
      await api('/api/draft/discard', { body: { draft_id: row.draft } });
      delete S.tableCache[table];
      await g.reload();
      await loadState();
      if (opts.onChange) opts.onChange(table);
    });
  };

  /** Where the cursor is, so a re-render of the screen (a refresh, a gate switch) can put it back. */
  g.cursorState = () => {
    const row = rowAt(g.cur.r);
    return { table, key: row ? row.key : null, c: g.cur.c, focused: document.activeElement === g.host, newRow: isNewRow(g.cur.r) };
  };
  g.restoreCursor = (st) => {
    if (!st || st.table !== table || g.edit) return;
    const at = st.key ? g.view.findIndex((x) => x.key === st.key) : -1;
    g.cur = { r: at >= 0 ? at : (st.newRow && !opts.noNew ? rowCount() : g.cur.r), c: Math.min(st.c, colCount() - 1) };
    Grid.current = g;
    paintCursor();
    if (st.focused) g.host.focus({ preventScroll: true });
  };

  g.focusKey = (key) => {
    const at = g.view.findIndex((x) => x.key === key);
    if (at >= 0) { g.select(at, g.cur.c); }
  };

  g.el = h('div', { class: 'grid-wrap' }, g.host, g.msg);
  g.host.addEventListener('focusin', () => { Grid.current = g; });
  proposeId().then(() => { if (!dead()) draw(); });
  draw();
  return g;
}

if (typeof module !== 'undefined' && module.exports) module.exports = { gridCompositeId };
