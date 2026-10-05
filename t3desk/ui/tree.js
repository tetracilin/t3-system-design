'use strict';
/* Decision tree drawing (section 6). Pure SVG, top-down, built for a 360 px wide panel.
 *
 * TreeView.draw(container, tree, options)
 *   tree     {questions:[{index,q,check,yes,no}], highlighted, steps:[{index,answer,ends_here}], leaf}
 *   options  {yesText, noText, onAction(screen), onLeaf(el)}  all text comes from the caller (labels file)
 *
 * Layout: one question box per row across the full width. A vertical "bus" line at the left
 * runs down from each question; written branches leave it into action boxes on the right,
 * and the branch that is NOT written continues down to the next question.
 */
const TreeView = (function () {
  const NS = 'http://www.w3.org/2000/svg';
  const W = 340;
  const BUS_X = 14;
  const Q_X = 2, Q_W = 336, Q_CHARS = 47;
  const A_X = 52, A_W = 286, A_CHARS = 40;
  const LINE = 15, PAD = 8, GAP = 16;

  function node(name, attrs, text) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function wrap(text, limit) {
    const lines = [];
    let line = '';
    for (const word of String(text).split(/\s+/)) {
      let w = word;
      while (w.length > limit) {
        if (line) { lines.push(line); line = ''; }
        lines.push(w.slice(0, limit));
        w = w.slice(limit);
      }
      if (!line) line = w;
      else if ((line + ' ' + w).length <= limit) line += ' ' + w;
      else { lines.push(line); line = w; }
    }
    if (line) lines.push(line);
    return lines;
  }

  function textBlock(svg, lines, x, y, cls) {
    const t = node('text', { x, y, class: cls });
    lines.forEach((ln, i) => t.appendChild(node('tspan', { x, dy: i === 0 ? 0 : LINE }, ln)));
    svg.appendChild(t);
  }

  function stepFor(tree, index) {
    return (tree.steps || []).find((s) => s.index === index) || null;
  }

  function draw(container, tree, options) {
    const opts = options || {};
    container.textContent = '';
    const svg = node('svg', { class: 'tree-svg', role: 'img', preserveAspectRatio: 'xMinYMin meet' });
    const lit = !!tree.highlighted;
    const cls = (base, on) => base + (lit ? (on ? ' on' : ' dim') : '');
    let y = 6;
    let leafEl = null;
    const qs = tree.questions;

    qs.forEach((q, qi) => {
      const step = stepFor(tree, q.index);
      const qOn = !!step;
      const qLines = wrap(q.q, Q_CHARS);
      const qh = qLines.length * LINE + PAD * 2 - 2;
      const group = node('g', { class: 'q-group', 'data-index': q.index });
      group.appendChild(node('rect', { x: Q_X, y, width: Q_W, height: qh, rx: 8, class: cls('q-box', qOn) }));
      textBlock(group, qLines, Q_X + PAD, y + PAD + 10, cls('q-text', qOn));
      svg.appendChild(group);

      let cursor = y + qh;
      const branches = ['yes', 'no'].filter((a) => q[a]);
      const forward = branches.length === 2 ? null : (q.yes ? 'no' : (q.no ? 'yes' : null));
      const hasNext = qi < qs.length - 1;
      let busFrom = cursor;
      const chosen = step && step.ends_here ? step.answer : null;

      branches.forEach((ans) => {
        const b = q[ans];
        const lines = wrap(b.do, A_CHARS);
        const isLeaf = tree.leaf && tree.leaf.index === q.index && tree.leaf.answer === ans;
        const top = cursor + GAP + (isLeaf ? 8 : 0);
        const h = lines.length * LINE + PAD * 2 - 2;
        const mid = top + h / 2;
        const on = chosen === ans;
        svg.appendChild(node('path', { d: `M${BUS_X} ${busFrom} V${mid} H${A_X}`, class: cls('edge', on), 'marker-end': 'url(#arrow)' }));
        svg.appendChild(node('text', { x: BUS_X + 3, y: mid - 3, class: cls('edge-label', on) }, ans === 'yes' ? opts.yesText : opts.noText));
        const g = node('g', { class: 'a-group' });
        const clickable = !!b.screen;
        const rect = node('rect', {
          x: A_X, y: top, width: A_W, height: h, rx: 8,
          class: cls('a-box', on) + (isLeaf ? ' here' : '') + (clickable ? ' link' : ''),
        });
        g.appendChild(rect);
        textBlock(g, lines, A_X + PAD, top + PAD + 10, cls('a-text', on));
        if (isLeaf) {
          const tag = tree.leaf.label || '';
          const tw = tag.length * 6.4 + 14;
          g.appendChild(node('rect', { x: A_X + A_W - tw - 6, y: top - 9, width: tw, height: 16, rx: 8, class: 'here-tag' }));
          g.appendChild(node('text', { x: A_X + A_W - tw - 6 + tw / 2, y: top + 3, 'text-anchor': 'middle', class: 'here-text' }, tag));
          leafEl = rect;
        }
        if (clickable) {
          g.setAttribute('tabindex', '0');
          g.setAttribute('role', 'button');
          const go = () => opts.onAction && opts.onAction(b.screen);
          g.addEventListener('click', go);
          g.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); go(); } });
        }
        svg.appendChild(g);
        busFrom = mid;
        cursor = top + h;
      });

      if (hasNext && forward) {
        const next = cursor + GAP + 10;
        const on = step && !step.ends_here && (step.answer === forward || step.answer === null);
        svg.appendChild(node('path', { d: `M${BUS_X} ${busFrom} V${next}`, class: cls('edge', !!on), 'marker-end': 'url(#arrow)' }));
        if (q.check) {
          svg.appendChild(node('text', { x: BUS_X + 4, y: next - 5, class: cls('edge-label', !!on) }, forward === 'yes' ? opts.yesText : opts.noText));
        }
        y = next;
      } else {
        y = cursor + GAP;
      }
    });

    const defs = node('defs');
    const marker = node('marker', { id: 'arrow', viewBox: '0 0 8 8', refX: 7, refY: 4, markerWidth: 6, markerHeight: 6, orient: 'auto' });
    marker.appendChild(node('path', { d: 'M0 0 L8 4 L0 8 z', class: 'arrow-head' }));
    defs.appendChild(marker);
    svg.insertBefore(defs, svg.firstChild);
    const height = Math.ceil(y + 8);
    svg.setAttribute('viewBox', `0 0 ${W} ${height}`);
    svg.setAttribute('width', '100%');
    svg.style.maxWidth = W * 1.6 + 'px';
    container.appendChild(svg);
    if (leafEl && opts.onLeaf) opts.onLeaf(leafEl);
    return svg;
  }

  return { draw, wrap };
})();
