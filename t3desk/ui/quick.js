'use strict';
/* Quick add: one popup, one button (bottom right) or Alt+A, to create and define a library item, a breakdown item,
 * a milestone, a decision, an RFQ or an RFP without first finding the right screen. It is a deliberate exception to
 * "no pop-up for adding": the button asked for it. It saves a draft like everything else; nothing reaches Teable
 * before Commit. Forms come from schema.yaml (labels, choices, reference lists) with a short list of fields to show. */

const QUICK_TYPES = [
  { key: 'node', label: 'qa_node' },
  { key: 'library', label: 'qa_library', table: 'hang_muc', go: 'thu_vien',
    show: ['ten', 'cap', 'loai', 'chuc_nang', 'hang', 'model', 'sku', 'nguoi_dien', 'trang_thai'] },
  { key: 'moc', label: 'qa_moc', table: 'moc', go: 'moc', tab: 'moc', show: ['ma_moc', 'ten', 'ngay_co_so', 'ngay_du_bao', 'trang_thai'] },
  { key: 'decision', label: 'qa_decision', table: 'quyet_dinh', go: 'moc', tab: 'quyet_dinh',
    show: ['cau_hoi', 'phuc_vu_moc', 'ngay_du_bao', 'ket_luan', 'ngay_ket_luan'] },
  { key: 'rfq', label: 'qa_rfq', table: 'rfq', go: 'rfq', fixed: { loai: 'RFQ' }, prefix: 'RFQ-',
    show: ['ds_ma_uv', 'nha_cung_cap', 'han_tra_loi', 'ghi_chu'] },
  { key: 'rfp', label: 'qa_rfp', table: 'rfq', go: 'rfq', fixed: { loai: 'RFP' }, prefix: 'RFP-',
    show: ['ds_ma_nut', 'nha_cung_cap', 'han_tra_loi', 'ghi_chu'] },
];

/** A form for one kind of record. Returns the element and a `save(keepOpen)` that talks to the server. */
async function quickTableForm(type, done) {
  const spec = specOf(type.table);
  const idName = spec.id_field;
  const refs = await refChoicesFor(spec);
  const inputs = {};
  const grid = h('div', { class: 'qa-fields' });
  const msg = h('div', { class: 'err', id: 'qa-error' });
  let proposed = '';
  const propose = async () => {
    if (spec.id.kind !== 'number') { proposed = ''; return; }
    const q = { table: type.table };
    if (type.prefix) q.prefix = type.prefix;
    try { proposed = (await api('/api/next_id', { query: q })).id || ''; } catch (e) { proposed = ''; }
  };
  await propose();
  const add = (name) => {
    const fs = spec.fields[name];
    const input = fieldInput(type.table, name, fs, fs.default, refs[fs.ref], 'qa-' + name);
    inputs[name] = input;
    grid.appendChild(h('div', { class: 'f' + (fs.type === 'longtext' ? ' wide' : ''), 'data-field': name },
      h('label', { for: input.id, text: fieldLabel(type.table, name) + (fs.required ? ' *' : '') }), input, input._datalist || null));
  };
  if (spec.id.kind === 'number') {
    grid.appendChild(h('div', { class: 'f', 'data-field': idName },
      h('label', { text: fieldLabel(type.table, idName) }), h('input', { type: 'text', id: 'qa-id', readonly: true, value: proposed }),
      h('span', { class: 'muted', text: T('qa_id_auto') })));
  }
  type.show.forEach(add);
  const clear = () => { for (const f of grid.querySelectorAll('.f')) { f.classList.remove('bad'); const w = f.querySelector('.why'); if (w) w.remove(); } msg.textContent = ''; };
  const save = async (keepOpen) => {
    clear();
    const fields = Object.assign({}, type.fixed || {});
    for (const name of type.show) {
      const v = readField(spec.fields[name], inputs[name]);
      if (v !== '') fields[name] = v;
    }
    if (spec.id.kind === 'number') fields[idName] = proposed;
    try {
      await api('/api/draft', { body: { table: type.table, op: 'create', fields } });
    } catch (e) {
      const err = e instanceof ApiFail ? e.err : {};
      if (err.code === 'invalid' && err.issues) {
        msg.textContent = T('err_invalid');
        for (const issue of err.issues) {
          const cell = grid.querySelector('[data-field="' + issue.field + '"]');
          if (cell) { cell.classList.add('bad'); cell.appendChild(h('span', { class: 'why', text: issueText(issue) })); }
        }
      } else showError(e);
      return;
    }
    delete S.tableCache[type.table];
    const key = fields[idName];
    toast(T('qa_saved', { what: tableLabel(type.table) + ' ' + key }));
    await done(type, key, keepOpen);
    if (keepOpen) {
      for (const name of type.show) { const fs = spec.fields[name]; inputs[name].value = fs.default || ''; }
      await propose();
      const idBox = grid.querySelector('#qa-id');
      if (idBox) idBox.value = proposed;
      const first = inputs[type.show[0]];
      if (first) first.focus();
    }
  };
  return { el: h('div', null, grid, msg), save };
}

/** Add something to the breakdown: an existing library item, or a new placeholder, under a chosen node. */
async function quickNodeForm(done) {
  const [lib, tree] = await Promise.all([api('/api/library'), api('/api/tree_nodes')]);
  const msg = h('div', { class: 'err', id: 'qa-error' });
  const labelOf = (it) => it.key + ' - ' + it.name;
  const item = h('input', { type: 'text', id: 'qa-item', list: 'qa-items', autocomplete: 'off', 'aria-label': T('qa_item_label') });
  const items = h('datalist', { id: 'qa-items' }, lib.items.map((it) => h('option', { value: labelOf(it) })));
  const who = h('input', { type: 'text', id: 'qa-who', list: 'qa-people', autocomplete: 'off', 'aria-label': T('lib_who') });
  const people = h('datalist', { id: 'qa-people' }, lib.people.map((p) => h('option', { value: p })));
  const open = tree.nodes.filter((n) => n.level < 2);
  const target = S.node && open.some((n) => n.code === S.node) ? S.node : (open[0] ? open[0].code : '');
  const parent = h('select', { id: 'qa-parent', 'aria-label': T('qa_parent') },
    open.map((n) => h('option', { value: n.code, selected: n.code === target, text: n.code + ' - ' + (n.name || T('node_unnamed')) + ' (' + capLabel(n.level) + ')' })));
  const arch = h('select', { id: 'qa-arch', 'aria-label': T('qa_arch') }, h('option', { value: '', text: T('qa_arch_none') }),
    tree.archs.map((a) => h('option', { value: a.key, selected: a.key === S.arch, text: a.key + ' - ' + a.name })));
  const qty = h('input', { type: 'text', id: 'qa-qty', inputmode: 'decimal', value: '1', 'aria-label': T('qa_qty') });
  const field = (label, el, extra) => h('div', { class: 'f', 'data-field': label }, h('label', { for: el.id, text: T(label) }), el, extra || null);
  const form = h('div', { class: 'qa-fields' },
    h('div', { class: 'f wide' }, h('label', { for: 'qa-item', text: T('qa_item_label') }), item, items, h('span', { class: 'muted', text: T('qa_item_hint') })),
    field('qa_who', who, people), field('qa_parent', parent), field('qa_arch', arch), field('qa_qty', qty));
  const save = async (keepOpen) => {
    msg.textContent = '';
    const text = item.value.trim();
    if (!text) { msg.textContent = T('qa_item_needed'); item.focus(); return; }
    const hit = lib.items.find((it) => text === labelOf(it) || text.toUpperCase() === it.key);
    const body = { parent: parent.value, ma_kt: arch.value || undefined, so_luong: qty.value.trim() || undefined };
    if (hit) body.item = hit.key; else body.new = { ten: text, nguoi_dien: who.value.trim() || undefined };
    try {
      const res = await api('/api/breakdown/add', { body });
      toast(T(res.created_item ? 'lib_created_placed' : 'lib_added', { node: res.node, item: res.item }));
      await done({ key: 'node' }, res.node, keepOpen);
      if (keepOpen) { item.value = ''; who.value = ''; item.focus(); }
    } catch (e) { showError(e); }
  };
  return { el: h('div', null, form, msg), save };
}

async function quickAddDialog(startKey) {
  let active = QUICK_TYPES.find((t) => t.key === startKey) || QUICK_TYPES[1];
  const area = h('div', { id: 'qa-area' });
  const tabs = h('div', { class: 'qa-tabs', role: 'tablist' });
  let form = null;

  const done = async (type, key, keepOpen) => {
    if (keepOpen) { await loadState(); return; }
    closeModal();
    if (type.key === 'node') { S.node = key; go('cay', { node: key }); return; }
    S.pendingSelect = { table: type.table, key };
    if (S.screen === type.go && (!type.tab || S.tabs[type.go] === type.tab)) await refreshAll();
    else go(type.go, type.tab ? { tab: type.tab } : undefined);
  };

  const show = async () => {
    for (const b of tabs.querySelectorAll('button')) b.setAttribute('aria-selected', String(b.dataset.type === active.key));
    area.textContent = '';
    area.appendChild(h('p', { class: 'muted', text: T('qa_loading') }));
    try { form = active.table ? await quickTableForm(active, done) : await quickNodeForm(done); } catch (e) { showError(e); return; }
    area.textContent = '';
    area.appendChild(form.el);
    const first = area.querySelector('input:not([readonly]), select, textarea');
    if (first) first.focus();
  };
  for (const t of QUICK_TYPES) {
    tabs.appendChild(h('button', { type: 'button', role: 'tab', 'data-type': t.key, text: T(t.label), onclick: () => { active = t; show(); } }));
  }
  const hint = h('span', { class: 'muted grow', text: T('qa_keys') });
  const dlg = modal(T('qa_title'), [tabs, area], [hint,
    h('button', { class: 'btn', type: 'button', text: T('btn_cancel'), onclick: closeModal }),
    h('button', { class: 'btn', type: 'button', id: 'qa-save-more', text: T('qa_save_more'), onclick: () => form && form.save(true) }),
    h('button', { class: 'btn primary', type: 'button', id: 'qa-save', text: T('qa_save'), onclick: () => form && form.save(false) })]);
  dlg.classList.add('quick');
  dlg.addEventListener('keydown', (ev) => {
    const single = ev.target && ev.target.tagName === 'INPUT';
    if ((ev.key === 'Enter' && single && !ev.target.readOnly) || (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey))) {
      ev.preventDefault();
      ev.stopPropagation();
      if (form) form.save(ev.shiftKey);
    }
  });
  await show();
}
