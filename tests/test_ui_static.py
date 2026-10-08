"""UI v2 acceptance tests that need no browser (docs/UI-V2-SPEC.md section 10).

1  four panes, pane 1 holds the menu and the tree
2  no pop-up for adding or editing a record
3  references list "code - name" (the names payload is tested in test_server.py)
4  every shortcut of section 8 is registered and labelled; every clickable thing can take focus
5  notes: the Markdown reader shows tags as text (the server rules are in test_server.py)
6  the Hermes placeholder is off without a plugin (the endpoint is tested in test_server.py)

Node is needed for the tests that run keys.js, notes.js and grid.js; they skip when it is missing.
Item 8 of the spec (tab through the four panes on each OS) is a manual check.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from t3desk import server

UI = Path(server.__file__).resolve().parent / "ui"
SCRIPTS = ("app.js", "notes.js", "grid.js", "keys.js")
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def read(name: str) -> str:
    return (UI / name).read_text(encoding="utf-8")


def labels() -> dict[str, str]:
    return server.load_ui_labels()["ui"]


def node_json(script: str) -> object:
    """Run a snippet in Node from the ui folder and return the JSON it prints."""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, cwd=UI, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# ---- 1: four panes -------------------------------------------------------------------------------


def test_four_panes_in_order_and_pane_1_holds_the_menu_and_the_tree() -> None:
    html = read("index.html")
    assert re.findall(r'<(?:section|aside)[^>]*\bid="(pane[1-4])"', html) == ["pane1", "pane2", "pane3", "pane4"]
    assert re.findall(r'data-pane="([1-4])"', html) == ["1", "2", "3", "4"]
    pane1 = html[html.index('id="pane1"'):html.index('id="pane2"')]
    assert 'id="nav"' in pane1 and 'id="tree-tabs"' in pane1 and 'id="tree-list"' in pane1
    assert 'id="p3-body"' in html and 'id="p4-body"' in html and "hermes" not in html  # pane 4 is filled by app.js
    assert 'id="shell"' in html and html.index('id="pane1"') < html.index('id="pane4"')


def test_script_order_defines_the_helpers_before_the_modules_use_them() -> None:
    html = read("index.html")
    order = re.findall(r'<script src="/([a-z]+\.js)">', html)
    assert order == ["tree.js", "app.js", "notes.js", "grid.js", "keys.js"]
    for name in order:
        assert (UI / name).is_file()


# ---- 2: no pop-up to add or edit ------------------------------------------------------------------

DIALOGS_THAT_REMAIN = {
    "chooseArchitecture",   # the reason for choosing an architecture (spec section 3)
    "conflictDialog", "staleDialog",  # commit: duplicate ID and stale edit, not adding or editing
    "closeFinding", "addNote",        # weekly review: a closing reason and the kind of remark
    "paletteDialog", "cheatSheet", "widenPanel",  # navigation help: Ctrl+K, ? and F1
}


def test_no_form_pop_up_for_adding_or_editing_a_record() -> None:
    sources = {n: read(n) for n in SCRIPTS}
    for name, src in sources.items():
        assert "openForm" not in src, name
        assert "openRow" not in src, name
        assert "form-grid" not in src and "S.form" not in src, name
    users = set()
    for name, src in sources.items():
        for chunk in re.split(r"\n(?=(?:async )?function \w+|const \w+ = \(?|SCREENS\.\w+ =)", src):
            if "modal(" not in chunk:
                continue
            head = re.match(r"(?:async )?function (\w+)", chunk)
            users.add(head.group(1) if head else chunk.split("\n", 1)[0][:50])
    assert users - {"modal"} <= DIALOGS_THAT_REMAIN, users


def test_the_grid_saves_every_cell_as_a_draft_through_the_same_api_call() -> None:
    src = read("grid.js")
    assert src.count("api('/api/draft'") == 1 and "partial: true" in src
    assert "base_modified: row.modified" in src and "draft_id: row.draft" in src  # the stale check still works
    assert "specOf(table)" in src and "spec.fields" in src  # columns come from the schema, not from the code


# ---- 4: keyboard ------------------------------------------------------------------------------------

# one sample key event (and where it is pressed) for every shortcut id
SAMPLES = {
    "panes": ({"altKey": True, "key": "3"}, {}),
    "pane_next": ({"key": "F6"}, {}),
    "tree_wide": ({"key": "F1"}, {}),
    "resize": ({"altKey": True, "shiftKey": True, "key": "ArrowRight"}, {}),
    "palette": ({"ctrlKey": True, "key": "k"}, {}),
    "goto": ({"key": "g"}, {}),
    "chart_move": ({"key": "ArrowDown"}, {"inChart": True}),
    "chart_select": ({"key": "Enter"}, {"inChart": True}),
    "chart_add": ({"ctrlKey": True, "shiftKey": True, "key": "N"}, {}),
    "gate": ({"key": " ", "target": {"dataset": {"gate": "chot_cap_1"}}}, {}),
    "cell_move": ({"key": "ArrowRight"}, {"inGrid": True}),
    "cell_edit": ({"key": "F2"}, {"inGrid": True}),
    "cell_commit": ({"key": "Enter"}, {"inGrid": True, "editing": True}),
    "cell_cancel": ({"key": "Escape"}, {"inGrid": True, "editing": True}),
    "cell_copy": ({"ctrlKey": True, "key": "d"}, {"inGrid": True}),
    "row_new": ({"ctrlKey": True, "shiftKey": True, "key": "Enter"}, {}),
    "tabs": ({"ctrlKey": True, "key": "PageDown"}, {}),
    "row_discard": ({"altKey": True, "key": "Backspace"}, {"inGrid": True}),
    "library_focus": ({"altKey": True, "key": "l"}, {}),
    "note_focus": ({"key": "n"}, {}),
    "note_save": ({"ctrlKey": True, "key": "Enter"}, {"inNote": True}),
    "note_preview": ({"altKey": True, "key": "p"}, {}),
    "hermes": ({"altKey": True, "key": "h"}, {}),
    "save": ({"ctrlKey": True, "key": "s"}, {}),
    "commit": ({"ctrlKey": True, "key": "Enter"}, {}),
    "help": ({"key": "?"}, {}),
}
# the keys of docs/UI-V2-SPEC.md section 8, as the cheat sheet shows them
SECTION_8 = ["Alt+1..4", "F6", "F1", "Ctrl+K", "G", "Ctrl+Shift+N", "Space", "F2", "Ctrl+D", "Ctrl+Shift+Enter",
             "Ctrl+PageUp", "Alt+Backspace", "Alt+P", "Alt+H", "Ctrl+S", "Ctrl+Enter", "?"]


@needs_node
def test_every_shortcut_of_section_8_is_registered_labelled_and_fires() -> None:
    out = node_json(
        "const k = require('./keys.js'); const s = {};"
        "for (const sc of k.SHORTCUTS) s[sc.id] = {keys: sc.keys, label: sc.label, run: typeof sc.run, match: typeof sc.match};"
        "console.log(JSON.stringify(s));"
    )
    assert set(out) == set(SAMPLES), set(out) ^ set(SAMPLES)
    ui = labels()
    for sid, entry in out.items():
        assert entry["run"] == "function" and entry["match"] == "function", sid
        assert ui.get(entry["label"]), f"{sid}: label {entry['label']} is missing"
    shown = " ".join(e["keys"] for e in out.values())
    for key in SECTION_8:
        assert key in shown, f"section 8 key {key} is not in the cheat sheet"
    # fire a sample event at every entry: exactly this entry must claim it
    cases = json.dumps({sid: [ev, ctx] for sid, (ev, ctx) in SAMPLES.items()})
    hits = node_json(
        "const k = require('./keys.js'); const cases = " + cases + "; const r = {};"
        "for (const [id, [ev, ctx]] of Object.entries(cases)) {"
        "  const base = {key: '', altKey: false, ctrlKey: false, metaKey: false, shiftKey: false, target: null};"
        "  const full = Object.assign({}, base, ev);"
        "  const c = Object.assign({pane: 0, typing: false, inGrid: false, inChart: false, inNote: false, editing: false}, ctx);"
        "  r[id] = k.SHORTCUTS.filter((sc) => sc.match(full, c)).map((sc) => sc.id);"
        "}"
        "console.log(JSON.stringify(r));"
    )
    for sid, claimed in hits.items():
        assert sid in claimed, f"{sid} does not react to its own key"
    # only pairs that are meant to share a key may overlap (Enter: grid vs chart vs commit stay apart by where it is pressed)
    for sid, claimed in hits.items():
        assert len(claimed) <= 2, (sid, claimed)


@needs_node
def test_letters_typed_into_a_field_never_trigger_a_shortcut() -> None:
    out = node_json(
        "const k = require('./keys.js'); const typing = {pane: 3, typing: true, inGrid: false, inChart: false, inNote: false, editing: false};"
        "const r = [];"
        "for (const ch of ['g', 'n', '?', 'r', 'k']) {"
        "  const ev = {key: ch, altKey: false, ctrlKey: false, metaKey: false, shiftKey: false, target: null};"
        "  r.push(k.SHORTCUTS.filter((sc) => sc.match(ev, typing)).map((sc) => sc.id));"
        "}"
        "console.log(JSON.stringify(r));"
    )
    assert out == [[], [], [], [], []]


@needs_node
def test_in_the_table_a_letter_edits_the_cell_and_the_alternatives_work_everywhere() -> None:
    out = node_json(
        "const k = require('./keys.js'); const base = {key: '', altKey: false, ctrlKey: false, metaKey: false, shiftKey: false, target: null};"
        "const grid = {pane: 3, typing: false, inGrid: true, inChart: false, inNote: false, editing: false};"
        "const ids = (ev, c) => k.SHORTCUTS.filter((sc) => sc.match(Object.assign({}, base, ev), c)).map((sc) => sc.id);"
        "console.log(JSON.stringify([ids({key: 'n'}, grid), ids({key: 'g'}, grid), ids({key: '?'}, grid),"
        " ids({key: 'n', altKey: true}, grid), ids({key: '/', ctrlKey: true}, grid), ids({key: 'k', ctrlKey: true}, grid)]));"
    )
    assert out == [["cell_edit"], ["cell_edit"], ["cell_edit"], ["note_focus"], ["help"], ["palette"]]


def test_every_clickable_thing_can_take_focus() -> None:
    app = read("app.js")
    # h() makes anything with a click handler focusable and gives it Enter and Space
    assert "props.onclick && !NO_FOCUS_TAGS.includes" in app and "setAttribute('tabindex', '0')" in app
    assert "ev.key === 'Enter' || ev.key === ' '" in app
    # the only raw click listeners left are on the toast (Esc closes it too) and are not on content
    listeners = [(n, m) for n in SCRIPTS for m in re.findall(r"getElementById\('([\w-]+)'\)\.addEventListener\('click'", read(n))]
    assert {m for _, m in listeners} <= {"toast", "panel-toggle", "panel-wide", "panel-strip"}, listeners
    html = read("index.html")
    for ident in ("panel-toggle", "panel-wide", "panel-strip"):
        assert re.search(r'<button[^>]*id="%s"' % ident, html), ident  # real buttons: focusable by default
    assert "Escape" in read("keys.js") and "toast" in read("keys.js")


# ---- 5: Markdown --------------------------------------------------------------------------------------


def test_no_script_assigns_html() -> None:
    for name in SCRIPTS + ("tree.js",):
        src = read(name)
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            assert banned not in src, f"{name} uses {banned}"


@needs_node
def test_markdown_reader_shows_tags_as_text_and_supports_the_listed_syntax() -> None:
    cases = {
        "tag": "<script>alert(1)</script> and <img src=x onerror=alert(1)>",
        "bold_italic_code": "**độ sâu** and *cần* and `x >= 20`",
        "heading": "## Tiêu đề",
        "list": "- một\n- hai\n1. ba",
        "fence": "```\n<b>not bold</b>\n```",
        "table": "| a | b |\n| - | - |\n| 1 | 2 |",
        "link": "[trang](https://example.com/a?b=1)",
        "js_link": "[bad](javascript:alert(1))",
        "image": "![x](https://example.com/p.png)",
        "empty": "",
    }
    out = node_json("const m = require('./notes.js'); const c = " + json.dumps(cases) +
                    "; const r = {}; for (const [k, v] of Object.entries(c)) r[k] = m.mdParse(v); console.log(JSON.stringify(r));")
    tag_types = {t["t"] for b in out["tag"] for t in b["c"]}
    assert tag_types == {"text"}  # nothing in the tag case turns into an element
    assert "<script>" in "".join(t["v"] for b in out["tag"] for t in b["c"])  # the characters are kept, shown as text
    kinds = [t["t"] for t in out["bold_italic_code"][0]["c"]]
    assert {"b", "i", "code"} <= set(kinds)
    assert out["heading"][0] == {"t": "h", "level": 2, "c": [{"t": "text", "v": "Tiêu đề"}]}
    assert [b["t"] for b in out["list"]] == ["ul", "ol"]
    assert out["fence"][0] == {"t": "code", "text": "<b>not bold</b>"}
    assert out["table"][0]["t"] == "table" and len(out["table"][0]["rows"]) == 1
    assert any(t["t"] == "a" and t["href"].startswith("https://") for t in out["link"][0]["c"])
    assert all(t["t"] != "a" for b in out["js_link"] for t in b["c"])  # only http(s) becomes a link
    assert all(t["t"] != "a" for b in out["image"] for t in b["c"])    # no external images
    assert out["empty"] == []


# ---- 6: Hermes placeholder ------------------------------------------------------------------------------


def test_hermes_panel_is_off_unless_the_server_says_a_plugin_supplies_actions() -> None:
    src = read("app.js")
    assert "disabled: !data.enabled" in src and "hermes-ask" in src
    assert "api('/api/assistant'" in src  # asking sends nothing anywhere: the endpoint only reports


@pytest.mark.skip(reason="UNVERIFIED: plugin actions are not wired to the screens yet (REQUIREMENTS 9.1); see STATUS.md")
def test_hermes_action_preview_shows_payload_and_host_without_price_budget_or_score() -> None:
    raise AssertionError("not built")


# ---- the grid (Node, no DOM) -------------------------------------------------------------------------------


@needs_node
def test_a_composite_id_is_built_from_its_parts_only_when_all_are_there() -> None:
    out = node_json(
        "global.h = () => null; global.S = {sort: {}}; const g = require('./grid.js');"
        "const spec = {id: {parts: ['ma_uv', 'ma_ts'], separator: '|'}};"
        "console.log(JSON.stringify([g.gridCompositeId(spec, {ma_uv: 'UV-001', ma_ts: 'TS-003'}),"
        " g.gridCompositeId(spec, {ma_uv: 'UV-001'}), g.gridCompositeId(spec, {})]));"
    )
    assert out == ["UV-001|TS-003", "", ""]
