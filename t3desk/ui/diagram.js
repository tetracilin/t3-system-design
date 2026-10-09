'use strict';
/* The system breakdown drawn as a diagram: the root on the left, children to the right, one box per component.
 * Plain HTML boxes and an SVG for the lines; no library. A box shows level, code, name, library item and the
 * architecture it belongs to. Click selects (pane 3 and 4 follow), "+" adds a child through Quick add, a library
 * item dragged from the library onto a box places it under that box. The diagram reads the same /api/tree_nodes
 * data as the list view, so both always show the same hierarchy. */

const DIAGRAM = { boxW: 230, boxH: 92, gapX: 36, gapY: 8, pad: 12 };

/** Position every visible node: x by depth, y by leaf order (a parent sits at the middle of its children). */
function diagramLayout(nodes, children, collapsed) {
  const pos = new Map();
  let nextRow = 0;
  const place = (n, depth) => {
    const kids = collapsed[n.code] ? [] : (children.get(n.code) || []);
    let row;
    if (!kids.length) { row = nextRow; nextRow += 1; } else {
      kids.forEach((k) => place(k, depth + 1));
      row = (pos.get(kids[0].code).row + pos.get(kids[kids.length - 1].code).row) / 2;
    }
    pos.set(n.code, { depth, row });
  };
  const known = new Set(nodes.map((n) => n.code));
  nodes.filter((n) => !n.parent || !known.has(n.parent)).forEach((n) => place(n, 0));
  return pos;
}

/** Draw into `host`. `ops` = { selected, onSelect(code), onAdd(code), onToggle(code), onDrop(code, text), archFilter }. */
function drawDiagram(host, data, children, ops) {
  host.textContent = '';
  const visible = data.nodes.filter((n) => !ops.archFilter || !n.arch || n.arch === ops.archFilter);
  const shown = new Set(visible.map((n) => n.code));
  const kids = new Map();
  for (const [parent, list] of children) kids.set(parent, list.filter((k) => shown.has(k.code)));
  const pos = diagramLayout(visible, kids, ops.collapsed || {});
  const D = DIAGRAM;
  const x = (depth) => D.pad + depth * (D.boxW + D.gapX);
  const y = (row) => D.pad + row * (D.boxH + D.gapY);
  let cols = 0;
  let rows = 0;
  for (const p of pos.values()) { cols = Math.max(cols, p.depth + 1); rows = Math.max(rows, p.row + 1); }
  const width = D.pad * 2 + cols * D.boxW + Math.max(0, cols - 1) * D.gapX;
  const height = D.pad * 2 + Math.max(rows, 1) * (D.boxH + D.gapY);
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', String(width));
  svg.setAttribute('height', String(height));
  svg.setAttribute('class', 'dg-lines');
  svg.setAttribute('aria-hidden', 'true');
  const canvas = h('div', { class: 'dg-canvas', id: 'dg-canvas', role: 'tree', style: 'width:' + width + 'px;height:' + height + 'px' });
  canvas.appendChild(svg);

  for (const n of visible) {
    const p = pos.get(n.code);
    if (!p) continue;
    for (const k of (kids.get(n.code) || [])) {
      const q = pos.get(k.code);
      if (!q || ops.collapsed[n.code]) continue;
      const x1 = x(p.depth) + D.boxW, y1 = y(p.row) + D.boxH / 2, x2 = x(q.depth), y2 = y(q.row) + D.boxH / 2, mid = (x1 + x2) / 2;
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('d', 'M' + x1 + ' ' + y1 + ' C' + mid + ' ' + y1 + ' ' + mid + ' ' + y2 + ' ' + x2 + ' ' + y2);
      path.setAttribute('class', 'dg-link');
      svg.appendChild(path);
    }
  }

  for (const n of visible) {
    const p = pos.get(n.code);
    if (!p) continue;
    const hasKids = (kids.get(n.code) || []).length > 0;
    const placeholder = n.item && n.item_status === S.meta.values.lib_placeholder;
    const box = h('div', {
      class: 'dg-box lvl-' + n.level + (n.code === ops.selected ? ' sel' : '') + (n.active === false ? ' inactive' : '') + (n.draft ? ' is-draft' : ''),
      role: 'treeitem', 'data-code': n.code, 'aria-selected': String(n.code === ops.selected), 'aria-label': n.code + ' ' + (n.name || ''),
      style: 'left:' + x(p.depth) + 'px;top:' + y(p.row) + 'px;width:' + D.boxW + 'px;height:' + D.boxH + 'px',
      onclick: () => ops.onSelect(n.code) },
      h('div', { class: 'dg-l1' }, h('span', { class: 'cap cap-' + n.level, text: capLabel(n.level) }), h('b', { class: 'code', text: n.code }),
        n.arch ? h('span', { class: 'chip arch', text: n.arch }) : null,
        n.warnings && n.warnings.length ? h('span', { class: 'badge warn', title: n.warnings.join('\n'), text: '! ' + n.warnings.length }) : null),
      h('div', { class: 'dg-name', title: n.name || '', text: n.name || T('node_unnamed') }),
      n.item ? h('span', { class: 'chip item' + (placeholder ? ' ph' : ''), text: n.item + (placeholder ? ' · ' + T('lib_placeholder_short') : '') }) : null);
    if (hasKids || ops.collapsed[n.code]) {
      box.appendChild(h('button', { type: 'button', class: 'dg-fold', 'data-fold': n.code, title: T('diagram_fold'), text: ops.collapsed[n.code] ? '▸' : '◂',
        onclick: (ev) => { ev.stopPropagation(); ops.onToggle(n.code); } }));
    }
    if (n.level < 2) {
      box.appendChild(h('button', { type: 'button', class: 'dg-add', 'data-add-child': n.code, title: T('diagram_add_child', { node: n.code }), text: '+',
        onclick: (ev) => { ev.stopPropagation(); ops.onAdd(n.code); } }));
    }
    box.addEventListener('dragover', (ev) => { if (n.level < 2) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'copy'; box.classList.add('drop'); } });
    box.addEventListener('dragleave', () => box.classList.remove('drop'));
    box.addEventListener('drop', (ev) => {
      box.classList.remove('drop');
      const text = ev.dataTransfer.getData(DROP_MIME) || '';
      if (n.level < 2 && text.startsWith('hm:')) { ev.preventDefault(); ops.onDrop(n.code, text.slice(3)); }
    });
    canvas.appendChild(box);
  }
  if (!visible.length) canvas.appendChild(h('p', { class: 'muted pad', text: T('empty') }));
  host.appendChild(h('div', { class: 'dg-scroll' }, canvas));
  const focus = canvas.querySelector('.dg-box.sel') || canvas.querySelector('.dg-box');
  if (focus) focus.scrollIntoView({ block: 'center', inline: 'nearest' }); // start where the selected box, or the root, is
  host.appendChild(h('div', { class: 'legend', text: T('diagram_legend') }));
}
