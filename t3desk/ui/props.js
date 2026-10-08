'use strict';
/* Field inputs (shared with Quick add) and the properties panel of pane 4.
 *
 * The panel shows and edits the selected component: its place in the breakdown (a node) and the library item it uses.
 * Every change is saved as a draft the moment a field is left, with the same rules as the table (stale check, partial
 * drafts, the reason shown under the field). Fields the library item supplies are shown on the node but cannot be
 * edited there: they are edited on the item, and the change shows in every place that uses it. */

/** One input for one schema field. Choices become a drop-down, references a list of `code - name`, numbers and dates text. */
function fieldInput(table, name, fs, value, refIds, id) {
  const common = { id, name, 'data-field': name, 'aria-label': fieldLabel(table, name) };
  let el;
  if (fs.type === 'choice') {
    el = h('select', common, h('option', { value: '', text: '' }), fs.choices.map((c) => h('option', { value: c, text: c, selected: c === value })));
  } else if (fs.type === 'longtext') {
    el = h('textarea', Object.assign({ rows: '2' }, common));
    el.value = value === undefined || value === null ? '' : value;
  } else {
    el = h('input', Object.assign({ type: 'text' }, common));
    el.value = value === undefined || value === null ? '' : String(value);
    if (fs.type === 'number') el.setAttribute('inputmode', 'decimal');
    if (fs.type === 'date') el.setAttribute('placeholder', 'YYYY-MM-DD');
    if (fs.ref && refIds) {
      const dl = h('datalist', { id: 'dl-' + id }, refIds.map((r) => h('option', { value: r, label: withName(fs.ref, r), text: withName(fs.ref, r) })));
      el.setAttribute('list', 'dl-' + id);
      el._datalist = dl;
    }
  }
  return el;
}

/** The value typed into an input, as the draft wants it: empty string, a number, or the text. */
function readField(fs, el) {
  const raw = el.value.trim();
  if (raw === '') return '';
  if (fs.type === 'number') {
    const n = Number(raw.replace(',', '.'));
    return Number.isFinite(n) ? n : raw; // a word in a number field comes back from the server as a reason
  }
  return raw;
}

async function refChoicesFor(spec) {
  const out = {};
  for (const name of Object.keys(spec.fields)) {
    const ref = spec.fields[name].ref;
    if (ref && !out[ref]) out[ref] = await idChoices(ref).catch(() => []);
  }
  return out;
}

/** One block of properties for one row. `heading` names it; the block keeps its own copy of the row so it can save again. */
async function propertyBlock(table, key, heading) {
  const data = await getRows(table);
  const row = data.rows.find((r) => r.key === key);
  if (!row) return null;
  const spec = specOf(table);
  const refs = await refChoicesFor(spec);
  const issues = {};
  const setIssues = (list) => { for (const k of Object.keys(issues)) delete issues[k]; for (const i of list || []) issues[i.field] = issueText(i); };
  setIssues(row.issues);
  const box = h('div', { class: 'props-block', 'data-props': table, 'data-key': key });
  const grid = h('div', { class: 'props' });
  const marks = h('span', { class: 'mark', text: row.draft ? ' ✎' : '' });
  box.appendChild(h('h4', { class: 'props-head' }, heading, marks));
  for (const name of Object.keys(spec.fields)) {
    if (name === spec.id_field) continue;
    const fs = spec.fields[name];
    const locked = !!(row.effective && row.effective[name] !== undefined);
    const shown = locked ? row.effective[name] : row.fields[name];
    const input = fieldInput(table, name, fs, shown, refs[fs.ref], 'prop-' + table + '-' + name);
    input.dataset.prop = name;
    if (locked) { input.setAttribute('disabled', ''); input.title = T('grid_from_library'); }
    const why = h('div', { class: 'why', text: issues[name] || '' });
    const cell = h('div', { class: 'p' + (fs.type === 'longtext' ? ' wide' : '') + (issues[name] ? ' bad' : '') + (locked ? ' locked' : ''), 'data-field': name },
      h('label', { for: input.id, text: fieldLabel(table, name) + (fs.required ? ' *' : '') }), input, input._datalist || null, why);
    if (!locked) {
      input.addEventListener('change', () => guard(async () => {
        const out = await saveRowField(table, row, name, readField(fs, input));
        if (out.res) {
          const draft = out.res.draft;
          row.draft = draft.id;
          row.draft_op = draft.op;
          row.fields = draft.op === 'create' ? draft.fields : Object.assign({}, row.fields, { [name]: readField(fs, input) });
          setIssues(draft.issues);
        } else if (out.discarded) {
          row.draft = null;
          row.draft_op = null;
          row.fields[name] = row.base ? row.base[name] : row.fields[name];
          setIssues([]);
        }
        marks.textContent = row.draft ? ' ✎' : '';
        for (const c of grid.querySelectorAll('.p')) {
          const bad = issues[c.dataset.field];
          c.classList.toggle('bad', !!bad);
          c.querySelector('.why').textContent = bad || '';
        }
        S.viewStale = true;
        await loadState();
      }));
    }
    grid.appendChild(cell);
  }
  box.appendChild(grid);
  box._row = row;
  box.addEventListener('focusout', (ev) => {
    if (S.viewStale && !(ev.relatedTarget && box.closest('#p4-body').contains(ev.relatedTarget))) {
      S.viewStale = false;
      render(); // the chart, the tables and the names catch up once you leave the panel
    }
  });
  return box;
}

/** Properties of the selected component: its place (the node), and the library item it uses when it has one. */
async function drawProperties(host, target) {
  host.textContent = '';
  if (!target) return;
  const wrap = h('details', { class: 'props-wrap', open: true }, h('summary', { text: T('props_title') }));
  host.appendChild(wrap);
  if (target.table === 'nut') {
    const place = await propertyBlock('nut', target.key, T('props_place', { node: withName('nut', target.key) }));
    if (place) wrap.appendChild(place);
    const item = place ? place._row.fields.ma_hm : '';
    if (item) {
      const block = await propertyBlock('hang_muc', item, T('props_item', { item: withName('hang_muc', item) }));
      if (block) wrap.appendChild(block);
    }
  } else if (target.table === 'hang_muc') {
    const block = await propertyBlock('hang_muc', target.key, T('props_item', { item: withName('hang_muc', target.key) }));
    if (block) wrap.appendChild(block);
  }
}
