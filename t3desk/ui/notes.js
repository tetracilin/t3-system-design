'use strict';
/* Notes (pane 4): a small Markdown reader and the notes thread of the selected row.
 *
 * mdParse() is a pure function (text -> blocks) so it can be tested in Node. mdRender() builds DOM
 * nodes with the h() helper from app.js: it never assigns HTML, so a <script> typed in a note is
 * shown as text and never run. Only http(s) links become links; images are not supported.
 * Supported: headings, bold, italic, inline code, code blocks, lists, links, tables. */

/* ---------- parser (pure) ---------- */

const MD_LINK = /^\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/;

function mdInline(text) {
  const out = [];
  let buf = '';
  const flush = () => { if (buf) { out.push({ t: 'text', v: buf }); buf = ''; } };
  let i = 0;
  while (i < text.length) {
    const rest = text.slice(i);
    let m;
    if ((m = /^`([^`\n]+)`/.exec(rest))) { flush(); out.push({ t: 'code', v: m[1] }); i += m[0].length; continue; }
    if ((m = /^\*\*([^\n]+?)\*\*/.exec(rest))) { flush(); out.push({ t: 'b', c: mdInline(m[1]) }); i += m[0].length; continue; }
    if ((m = /^\*([^*\s][^*\n]*?)\*/.exec(rest)) || (m = /^_([^_\s][^_\n]*?)_(?![A-Za-z0-9])/.exec(rest))) {
      flush(); out.push({ t: 'i', c: mdInline(m[1]) }); i += m[0].length; continue;
    }
    if ((m = /^!\[[^\]\n]*\]\([^\s)]*\)/.exec(rest))) { buf += m[0]; i += m[0].length; continue; } // images stay text
    if ((m = MD_LINK.exec(rest))) { flush(); out.push({ t: 'a', href: m[2], c: mdInline(m[1]) }); i += m[0].length; continue; }
    buf += text[i];
    i += 1;
  }
  flush();
  return out;
}

function mdCells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
}

function mdParse(source) {
  const lines = String(source === undefined || source === null ? '' : source).replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    let m;
    if (/^```/.test(line)) {
      const body = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) { body.push(lines[i]); i += 1; }
      i += 1; // the closing fence (or the end of the text)
      blocks.push({ t: 'code', text: body.join('\n') });
      continue;
    }
    if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) { blocks.push({ t: 'h', level: m[1].length, c: mdInline(m[2]) }); i += 1; continue; }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i]) && /^\s*\d+\./.test(lines[i]) === ordered) {
        items.push(mdInline(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, '')));
        i += 1;
      }
      blocks.push({ t: ordered ? 'ol' : 'ul', items });
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      const head = mdCells(line).map(mdInline);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(mdCells(lines[i]).map(mdInline)); i += 1; }
      blocks.push({ t: 'table', head, rows });
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(```|#{1,6}\s|\s*([-*]|\d+\.)\s+)/.test(lines[i])) { para.push(lines[i]); i += 1; }
    blocks.push({ t: 'p', c: mdInline(para.join('\n')) });
  }
  return blocks;
}

/* ---------- renderer (DOM, no HTML strings) ---------- */

function mdInlineNodes(tokens) {
  return tokens.map((tok) => {
    if (tok.t === 'text') return document.createTextNode(tok.v);
    if (tok.t === 'code') return h('code', { text: tok.v });
    if (tok.t === 'b') return h('strong', null, mdInlineNodes(tok.c));
    if (tok.t === 'i') return h('em', null, mdInlineNodes(tok.c));
    if (tok.t === 'a') return h('a', { href: tok.href, target: '_blank', rel: 'noopener noreferrer', title: tok.href }, mdInlineNodes(tok.c));
    return document.createTextNode('');
  });
}

function mdRender(source) {
  const box = h('div', { class: 'md' });
  for (const b of mdParse(source)) {
    if (b.t === 'h') box.appendChild(h('h' + Math.min(b.level + 2, 6), { class: 'md-h' }, mdInlineNodes(b.c)));
    else if (b.t === 'p') box.appendChild(h('p', null, mdInlineNodes(b.c)));
    else if (b.t === 'code') box.appendChild(h('pre', null, h('code', { text: b.text })));
    else if (b.t === 'ul' || b.t === 'ol') box.appendChild(h(b.t, null, b.items.map((it) => h('li', null, mdInlineNodes(it)))));
    else if (b.t === 'table') {
      box.appendChild(h('table', { class: 'md-table' },
        h('thead', null, h('tr', null, b.head.map((c) => h('th', null, mdInlineNodes(c))))),
        h('tbody', null, b.rows.map((r) => h('tr', null, r.map((c) => h('td', null, mdInlineNodes(c))))))));
    }
  }
  return box;
}

/* ---------- the notes thread of one row ---------- */

function noteTime(iso) {
  if (!iso) return T('note_draft_time');
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const p = (n) => String(n).padStart(2, '0');
  return p(d.getDate()) + '/' + p(d.getMonth() + 1) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}

/** Wrap the selected text of a textarea (or insert the markers when nothing is selected). */
function mdWrap(area, before, after) {
  const a = area.selectionStart, b = area.selectionEnd, v = area.value;
  area.value = v.slice(0, a) + before + v.slice(a, b) + after + v.slice(b);
  area.focus();
  area.selectionStart = a + before.length;
  area.selectionEnd = b + before.length;
}

/** The composer: Compose / Preview tabs, a small toolbar, and "who writes". `onSave(text)` does the saving. */
function noteComposer(opts) {
  const area = h('textarea', { id: opts.id || 'note-text', class: 'note-text', rows: '3', 'aria-label': T('note_compose') });
  area.value = opts.value || '';
  const preview = h('div', { class: 'note-preview', hidden: true });
  const setMode = (view) => {
    preview.hidden = !view;
    area.hidden = view;
    if (view) { preview.textContent = ''; preview.appendChild(mdRender(area.value)); }
    tabs.compose.setAttribute('aria-selected', String(!view));
    tabs.preview.setAttribute('aria-selected', String(view));
    (view ? tabs.preview : area).focus(); // focus stays inside the composer, so its keys keep working
  };
  const tabs = {
    compose: h('button', { class: 'btn small', type: 'button', role: 'tab', id: 'note-compose-tab', text: T('note_compose'), onclick: () => setMode(false) }),
    preview: h('button', { class: 'btn small', type: 'button', role: 'tab', id: 'note-preview-tab', text: T('note_preview'), onclick: () => setMode(true) }),
  };
  const tool = (label, title, fn) => h('button', { class: 'btn small', type: 'button', title, text: label, onclick: fn });
  const save = async () => {
    const text = area.value.trim();
    if (!text) { area.focus(); return; }
    await opts.onSave(text);
  };
  area.addEventListener('keydown', (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') { ev.preventDefault(); ev.stopPropagation(); guard(save); }
    if (ev.altKey && (ev.key === 'p' || ev.key === 'P')) { ev.preventDefault(); ev.stopPropagation(); setMode(preview.hidden); }
  });
  const box = h('div', { class: 'note-composer' },
    h('div', { class: 'note-bar' }, h('span', { class: 'muted', text: T('note_author', { who: (S.st && S.st.user) || T('none') }) }),
      tool('B', T('note_bold'), () => mdWrap(area, '**', '**')), tool('I', T('note_italic'), () => mdWrap(area, '*', '*')),
      tool('</>', T('note_code'), () => mdWrap(area, '`', '`')), tool('•', T('note_list'), () => mdWrap(area, '- ', '')),
      tool('🔗', T('note_link'), () => mdWrap(area, '[', '](https://)')), tabs.compose, tabs.preview),
    area, preview,
    h('div', { class: 'note-actions' }, opts.onCancel ? h('button', { class: 'btn small', type: 'button', text: T('btn_cancel'), onclick: opts.onCancel }) : null,
      h('button', { class: 'btn primary small', type: 'button', id: opts.saveId || 'btn-note-save', text: opts.saveText || T('note_save'), onclick: () => guard(save) })));
  tabs.compose.setAttribute('aria-selected', 'true');
  return box;
}

async function drawNotes(box, table, key) {
  box.textContent = '';
  if (!key) return;
  const data = await api('/api/notes', { query: { table, key } });
  box.appendChild(h('h3', { class: 'pane-sub' }, T('notes_title', { key }), ' ', h('span', { class: 'badge', id: 'note-count', text: String(data.notes.length) })));
  const changed = async () => { delete S.tableCache.ghi_chu; await loadState(); await drawNotes(box, table, key); if (window.onNotesChanged) window.onNotesChanged(); };
  const send = async (body) => { await api('/api/draft', { body }); toast(T('draft_saved')); await changed(); };
  for (const n of data.notes) {
    const head = h('div', { class: 'note-head' }, h('b', { text: n.author }), ' ', h('span', { class: 'muted', text: noteTime(n.modified || n.created) }),
      n.edited ? h('span', { class: 'badge', text: T('note_edited') }) : null, n.draft ? h('span', { class: 'badge draft', text: T('draft_mark') }) : null);
    const card = h('div', { class: 'note', 'data-note': n.key });
    const show = () => {
      card.textContent = '';
      card.appendChild(head);
      card.appendChild(mdRender(n.text));
      if (n.mine) {
        card.appendChild(h('div', { class: 'note-actions' },
          h('button', { class: 'btn small', type: 'button', 'data-edit-note': n.key, text: T('btn_edit'), onclick: edit }),
          h('button', { class: 'btn small', type: 'button', 'data-retire-note': n.key, text: T('note_retire'), onclick: () => guard(retire) })));
      }
    };
    const patch = (fields) => (n.draft
      ? { table: 'ghi_chu', op: 'update', key: n.key, draft_id: n.draft, fields }
      : { table: 'ghi_chu', op: 'update', key: n.key, record_id: n.record_id, base_modified: n.modified, base_fields: n.base, fields });
    const retire = async () => send(patch({ trang_thai: S.meta.values.cancelled }));
    const edit = () => {
      card.textContent = '';
      card.appendChild(head);
      card.appendChild(noteComposer({ id: 'note-edit-' + n.key, saveId: 'btn-note-update', value: n.text, saveText: T('note_save_edit'),
        onCancel: show, onSave: (text) => send(patch({ noi_dung: text })) }));
    };
    show();
    box.appendChild(card);
  }
  box.appendChild(noteComposer({
    onSave: async (text) => {
      const proposed = await api('/api/next_id', { query: { table: 'ghi_chu' } });
      await send({ table: 'ghi_chu', op: 'create', fields: { ma_gc: proposed.id, bang: table, ma_ban_ghi: key, noi_dung: text } });
    },
  }));
}

if (typeof module !== 'undefined' && module.exports) module.exports = { mdParse, mdInline };
