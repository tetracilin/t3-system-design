'use strict';
/* Keyboard model (docs/UI-V2-SPEC.md section 8): every action is reachable without the mouse.
 *
 * SHORTCUTS is the one list of shortcuts. Each entry has `keys` (shown in the cheat sheet), `label` (a key in
 * labels_ui_vi.yaml), `match(ev, ctx)` and `run(ev, ctx)`. One dispatcher reads the list, so a shortcut that
 * is listed is registered, and the Node test can fire a synthetic key event at every entry.
 * The components expose small APIs that these handlers call: Grid.current (grid.js), Chart.current (app.js),
 * Workspace (app.js). All are looked up when a key is pressed, never at load. */

const withMod = (ev) => ev.ctrlKey || ev.metaKey;
const isKey = (ev, ...names) => names.includes(ev.key);
const GOTO = { r: 'yeu_cau', k: 'kien_truc', c: 'cay', p: 'phan_bo', n: 'nut', m: 'mua_hang', d: 'commit' };
let gotoArmedAt = 0;

/** Where the key was pressed: which pane, whether the user is typing into a field, whether a cell is open. */
function keyContext(ev) {
  const target = ev.target && ev.target.closest ? ev.target : null;
  const pane = target ? target.closest('.pane') : null;
  const typing = !!target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable);
  const grid = typeof Grid !== 'undefined' ? Grid.current : null;
  return {
    pane: pane ? Number(pane.dataset.pane) : 0,
    typing,
    inGrid: !!target && !!target.closest('.grid-host'),
    inChart: !!target && !!target.closest('#chart'),
    inNote: !!target && !!target.closest('.note-composer'),
    editing: !!grid && grid.isEditing(),
  };
}

const SHORTCUTS = [
  // panes
  { id: 'panes', keys: 'Alt+1..4', label: 'sc_panes',
    match: (ev) => ev.altKey && !ev.shiftKey && /^[1-4]$/.test(ev.key),
    run: (ev) => focusPane(Number(ev.key)) },
  { id: 'pane_next', keys: 'F6 / Shift+F6', label: 'sc_pane_next',
    match: (ev) => ev.key === 'F6',
    run: (ev, c) => focusPane(((c.pane || 3) - 1 + (ev.shiftKey ? 3 : 1)) % 4 + 1) },
  { id: 'tree_wide', keys: 'F1', label: 'sc_tree_wide',
    match: (ev) => ev.key === 'F1',
    run: () => widenPanel() },
  { id: 'resize', keys: 'Alt+Shift+← / →', label: 'sc_resize',
    match: (ev) => ev.altKey && ev.shiftKey && isKey(ev, 'ArrowLeft', 'ArrowRight'),
    run: (ev, c) => resizePane(c.pane || 3, ev.key === 'ArrowRight' ? 40 : -40) },
  // sections
  { id: 'palette', keys: 'Ctrl+K', label: 'sc_palette',
    match: (ev) => withMod(ev) && !ev.shiftKey && !ev.altKey && (ev.key === 'k' || ev.key === 'K'),
    run: () => paletteDialog() },
  { id: 'goto', keys: 'G, then R K C P N M D (outside the table)', label: 'sc_goto',
    match: (ev, c) => !c.typing && !c.inGrid && !withMod(ev) && !ev.altKey && (isKey(ev, 'g', 'G') || (gotoArmedAt && Date.now() - gotoArmedAt < 1500 && GOTO[String(ev.key).toLowerCase()])),
    run: (ev) => {
      const k = String(ev.key).toLowerCase();
      if (k === 'g' && !(gotoArmedAt && Date.now() - gotoArmedAt < 1500)) { gotoArmedAt = Date.now(); return; }
      const screen = GOTO[k];
      gotoArmedAt = 0;
      if (screen) go(screen);
    } },
  // chart (pane 2)
  { id: 'chart_move', keys: '↑ ↓ ← →', label: 'sc_chart_move',
    match: (ev, c) => c.inChart && isKey(ev, 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight') && !withMod(ev) && !ev.altKey,
    run: (ev) => Chart.current && Chart.current.arrow(ev.key) },
  { id: 'chart_select', keys: 'Enter', label: 'sc_chart_select',
    match: (ev, c) => c.inChart && ev.key === 'Enter' && !ev.shiftKey && !withMod(ev),
    run: () => Chart.current && Chart.current.choose() },
  { id: 'chart_add', keys: 'Ctrl+Shift+N', label: 'sc_chart_add',
    match: (ev) => withMod(ev) && ev.shiftKey && (ev.key === 'n' || ev.key === 'N'),
    run: () => Chart.current && Chart.current.addChild() },
  { id: 'gate', keys: 'Space', label: 'sc_gate',
    match: (ev) => ev.key === ' ' && !!ev.target && !!ev.target.dataset && !!ev.target.dataset.gate,
    run: () => { /* a focused gate switch toggles natively; this entry documents it */ } },
  { id: 'quick_add', keys: 'Alt+A', label: 'sc_quick_add',
    match: (ev) => ev.altKey && !ev.shiftKey && !withMod(ev) && (ev.key === 'a' || ev.key === 'A'),
    run: () => { quickAddDialog(); } },
  { id: 'library_focus', keys: 'Alt+L', label: 'sc_library',
    match: (ev) => ev.altKey && !ev.shiftKey && (ev.key === 'l' || ev.key === 'L'),
    run: () => {
      const el = document.getElementById('lib-search') || document.getElementById('lib-new');
      if (el) { el.focus(); return; }
      go('thu_vien');
    } },
  // table (pane 3)
  { id: 'cell_move', keys: '← ↑ ↓ →, Tab, Shift+Tab', label: 'sc_cell_move',
    match: (ev, c) => c.inGrid && (isKey(ev, 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Tab') && !withMod(ev) && !ev.altKey)
      && !(c.editing && isKey(ev, 'ArrowUp', 'ArrowDown') && Grid.current && Grid.current.hasMenu()),
    run: (ev, c) => {
      const g = Grid.current;
      if (!g) return;
      if (ev.key === 'Tab') return g.commit(ev.shiftKey ? 'left' : 'right');
      if (c.editing && isKey(ev, 'ArrowLeft', 'ArrowRight')) return false; // the caret moves inside the field
      if (c.editing) return g.commit(ev.key === 'ArrowUp' ? 'up' : 'down');
      g.move(ev.key === 'ArrowUp' ? -1 : ev.key === 'ArrowDown' ? 1 : 0, ev.key === 'ArrowLeft' ? -1 : ev.key === 'ArrowRight' ? 1 : 0);
    } },
  { id: 'cell_edit', keys: 'F2, or just type', label: 'sc_cell_edit',
    match: (ev, c) => c.inGrid && !c.editing && !withMod(ev) && !ev.altKey && (ev.key === 'F2' || (ev.key.length === 1 && ev.key !== ' ')),
    run: (ev) => Grid.current && Grid.current.startEdit(ev.key === 'F2' ? null : ev.key) },
  { id: 'cell_commit', keys: 'Enter', label: 'sc_cell_commit',
    match: (ev, c) => c.inGrid && ev.key === 'Enter' && !withMod(ev) && !ev.altKey && !(ev.shiftKey && c.editing),
    run: (ev, c) => { const g = Grid.current; if (!g) return; if (c.editing) g.commit('down'); else g.startEdit(null); } },
  { id: 'cell_cancel', keys: 'Esc', label: 'sc_cell_cancel',
    match: (ev, c) => c.inGrid && c.editing && ev.key === 'Escape',
    run: () => Grid.current && Grid.current.cancel() },
  { id: 'cell_copy', keys: 'Ctrl+D', label: 'sc_cell_copy',
    match: (ev, c) => c.inGrid && withMod(ev) && (ev.key === 'd' || ev.key === 'D'),
    run: () => Grid.current && Grid.current.copyAbove() },
  { id: 'row_new', keys: 'Ctrl+Shift+Enter', label: 'sc_row_new',
    match: (ev) => withMod(ev) && ev.shiftKey && ev.key === 'Enter',
    run: () => Grid.current && Grid.current.newRow() },
  { id: 'tabs', keys: 'Ctrl+PageUp / PageDown', label: 'sc_tabs',
    match: (ev) => withMod(ev) && isKey(ev, 'PageUp', 'PageDown'),
    run: (ev) => Workspace.tab(ev.key === 'PageDown' ? 1 : -1) },
  { id: 'row_discard', keys: 'Alt+Backspace', label: 'sc_row_discard',
    match: (ev, c) => c.inGrid && ev.altKey && ev.key === 'Backspace',
    run: () => Grid.current && Grid.current.discardRow() },
  // notes and Hermes (pane 4)
  { id: 'note_focus', keys: 'N (outside the table), Alt+N', label: 'sc_note_focus',
    match: (ev, c) => (ev.key === 'n' || ev.key === 'N') && !withMod(ev)
      && ((ev.altKey && !ev.shiftKey) || (!ev.altKey && !c.typing && !c.inGrid)),
    run: () => { const el = document.getElementById('note-text'); if (el) el.focus(); } },
  { id: 'note_save', keys: 'Ctrl+Enter (in the note box)', label: 'sc_note_save',
    match: (ev, c) => c.inNote && withMod(ev) && ev.key === 'Enter',
    run: (ev) => {
      const box = ev.target && ev.target.closest ? ev.target.closest('.note-composer') : null;
      const save = box ? box.querySelector('.note-actions .primary') : null;
      if (save) save.click();
    } },
  { id: 'note_preview', keys: 'Alt+P', label: 'sc_note_preview',
    match: (ev) => ev.altKey && !ev.shiftKey && (ev.key === 'p' || ev.key === 'P'),
    run: () => {
      const preview = document.getElementById('note-preview-tab');
      const compose = document.getElementById('note-compose-tab');
      if (!preview || !compose) return;
      (preview.getAttribute('aria-selected') === 'true' ? compose : preview).click();
    } },
  { id: 'hermes', keys: 'Alt+H', label: 'sc_hermes',
    match: (ev) => ev.altKey && !ev.shiftKey && (ev.key === 'h' || ev.key === 'H'),
    run: () => { const el = document.getElementById('hermes-ask'); focusPane(4); if (el) el.focus(); } },
  // global
  { id: 'save', keys: 'Ctrl+S', label: 'sc_save',
    match: (ev) => withMod(ev) && !ev.shiftKey && (ev.key === 's' || ev.key === 'S'),
    run: () => { if (Grid.current && Grid.current.isEditing()) Grid.current.commit('none'); else toast(T('saved_already')); } },
  { id: 'commit', keys: 'Ctrl+Enter', label: 'sc_commit',
    match: (ev, c) => withMod(ev) && !ev.shiftKey && ev.key === 'Enter' && !c.inNote,
    run: () => commitNow() },
  { id: 'help', keys: '? (outside the table), Ctrl+/', label: 'sc_help',
    match: (ev, c) => (!c.typing && !c.inGrid && ev.key === '?') || (withMod(ev) && ev.key === '/'),
    run: () => cheatSheet() },
];

function dispatchKey(ev) {
  const ctx = keyContext(ev);
  for (const sc of SHORTCUTS) {
    if (!sc.match(ev, ctx)) continue;
    const res = sc.run(ev, ctx);
    if (res === false) return false; // let the browser handle it (for example the caret inside a field)
    ev.preventDefault();
    return true;
  }
  return false;
}

/* ---------- panes ---------- */

function focusPane(n) {
  const pane = document.querySelector('.pane[data-pane="' + n + '"]');
  if (!pane) return;
  const target = pane.querySelector('[data-focus-first]') || pane.querySelector('[tabindex="0"], button, input, select, textarea, a[href]') || pane;
  if (!target.hasAttribute('tabindex') && target === pane) pane.setAttribute('tabindex', '-1');
  target.focus();
  for (const p of document.querySelectorAll('.pane')) p.classList.toggle('focused', p === pane);
}

const PANE_VAR = { 1: '--p1w', 2: '--p2w', 4: '--p4w' };

/** Set the width of pane 1, 2 or 4 (pane 3 takes what is left). Capped so pane 3 keeps at least 360 px. */
function setPaneWidth(n, width) {
  const key = PANE_VAR[n];
  if (!key) return;
  const root = document.documentElement;
  const others = [1, 2, 4].filter((x) => x !== n).reduce((sum, x) => sum + (parseInt(getComputedStyle(root).getPropertyValue(PANE_VAR[x]), 10) || 0), 0);
  const room = Math.max(180, window.innerWidth - others - 360);
  const next = Math.max(n === 1 ? 44 : 180, Math.min(room, Math.round(width)));
  root.style.setProperty(key, next + 'px');
  try { localStorage.setItem('t3' + key, String(next)); } catch (e) { /* storage may be blocked: the width still applies */ }
}

function resizePane(n, delta) {
  const key = PANE_VAR[n];
  if (!key) return;
  setPaneWidth(n, (parseInt(getComputedStyle(document.documentElement).getPropertyValue(key), 10) || 300) + delta);
}

/** Drag handles between the panes, and between the chart and the library in pane 2. Arrow keys work on a focused handle. */
function addSplitter(pane, n, side) {
  const bar = h('div', { class: 'splitter ' + side, role: 'separator', 'aria-orientation': 'vertical', tabindex: '0', title: T('splitter_title'), 'data-splitter': String(n) });
  bar.addEventListener('pointerdown', (ev) => {
    ev.preventDefault();
    bar.setPointerCapture(ev.pointerId);
    const left = pane.getBoundingClientRect().left;
    const right = pane.getBoundingClientRect().right;
    const move = (e) => setPaneWidth(n, side === 'right' ? e.clientX - left : right - e.clientX);
    const stop = () => { bar.removeEventListener('pointermove', move); bar.removeEventListener('pointerup', stop); bar.classList.remove('drag'); };
    bar.classList.add('drag');
    bar.addEventListener('pointermove', move);
    bar.addEventListener('pointerup', stop);
  });
  bar.addEventListener('keydown', (ev) => {
    if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
    ev.preventDefault();
    ev.stopPropagation();
    const grow = (side === 'right') === (ev.key === 'ArrowRight');
    resizePane(n, grow ? 40 : -40);
  });
  bar.addEventListener('dblclick', () => { document.documentElement.style.removeProperty(PANE_VAR[n]); try { localStorage.removeItem('t3' + PANE_VAR[n]); } catch (e) { /* ignore */ } });
  pane.appendChild(bar);
}

function initChrome() {
  addSplitter(document.getElementById('pane1'), 1, 'right');
  addSplitter(document.getElementById('pane2'), 2, 'right');
  addSplitter(document.getElementById('pane4'), 4, 'left');
  document.getElementById('quick-add').addEventListener('click', () => quickAddDialog());
}

/* ---------- command palette (Ctrl+K) and cheat sheet (?) ---------- */

function paletteItems() {
  const items = S.meta.screens.map((s) => ({ label: T('nav_' + s), kind: T('pal_screen'), run: () => go(s) }));
  const add = (ref, kind, run) => {
    for (const code of Object.keys((S.names || {})[ref] || {})) {
      const text = S.names[ref][code];
      items.push({ label: code + ' - ' + text, kind, run: () => run(code) });
    }
  };
  add('nut', T('pal_node'), (c) => jumpTo('nut', c));
  add('yeu_cau', T('pal_requirement'), (c) => jumpTo('yeu_cau', c));
  add('kien_truc', T('pal_architecture'), (c) => jumpTo('kien_truc', c));
  add('ung_vien', T('pal_candidate'), (c) => jumpTo('ung_vien', c));
  add('thong_so', T('pal_spec'), (c) => jumpTo('thong_so', c));
  return items;
}

function paletteDialog() {
  const input = h('input', { id: 'palette-input', type: 'text', 'aria-label': T('pal_title'), placeholder: T('pal_title'), autocomplete: 'off' });
  const list = h('ul', { class: 'plain palette-list', id: 'palette-list', role: 'listbox' });
  const all = paletteItems();
  let shown = [];
  let at = 0;
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    shown = all.filter((i) => !q || i.label.toLowerCase().includes(q)).slice(0, 40);
    at = Math.min(at, Math.max(shown.length - 1, 0));
    list.textContent = '';
    shown.forEach((it, i) => list.appendChild(h('li', { role: 'option', 'aria-selected': String(i === at), class: i === at ? 'on' : '',
      onclick: () => { closeModal(); it.run(); } }, h('span', { class: 'muted', text: it.kind + '  ' }), it.label)));
    if (!shown.length) list.appendChild(h('li', { class: 'muted', text: T('empty') }));
  };
  input.addEventListener('input', () => { at = 0; draw(); });
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowDown') { ev.preventDefault(); ev.stopPropagation(); at = Math.min(at + 1, shown.length - 1); draw(); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); ev.stopPropagation(); at = Math.max(at - 1, 0); draw(); }
    else if (ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); const it = shown[at]; if (it) { closeModal(); it.run(); } }
  });
  modal(T('pal_title'), [input, list], [h('button', { class: 'btn', type: 'button', text: T('btn_close'), onclick: closeModal })]);
  draw();
}

function cheatSheet() {
  const rows = SHORTCUTS.map((s) => h('tr', null, h('td', null, h('kbd', { text: s.keys })), h('td', { text: T(s.label) })));
  modal(T('sc_title'), [h('table', { class: 'grid', id: 'cheat-sheet' }, h('tbody', null, rows))],
    [h('button', { class: 'btn primary', type: 'button', text: T('btn_close'), onclick: closeModal })]);
}

if (typeof document !== 'undefined') {
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && document.getElementById('modal-root').firstChild) { closeModal(); return; }
    if (ev.key === 'Escape') { const t = document.getElementById('toast'); if (t && !t.hidden) { t.hidden = true; return; } }
    dispatchKey(ev);
  });
}

if (typeof module !== 'undefined' && module.exports) module.exports = { SHORTCUTS, dispatchKey, keyContext };
