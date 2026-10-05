"""Decision tree loader and evaluator (section 6). No UI code.

The trees are data in data/decision_tree.yaml. Each tree is a list of questions run in
order. A question may name a ``check`` from rules.CHECKS; a true check takes the ``yes``
branch and a false one the ``no`` branch. A branch that is not written means "go to the
next question". The first branch that is written ends the walk: it is the leaf, shown
as "Bạn đang ở đây".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from t3desk import rules

DEFAULT_PATH = rules.DATA_DIR / "decision_tree.yaml"
TREE_NAMES = ("system_design", "designer", "engineer")


class DecisionTreeError(ValueError):
    """The decision tree file is missing, malformed or names an unknown check."""


@dataclass(frozen=True)
class Branch:
    do: str
    screen: str | None = None


@dataclass(frozen=True)
class Question:
    index: int
    q: str
    check: str | None = None
    yes: Branch | None = None
    no: Branch | None = None


@dataclass(frozen=True)
class Step:
    """One question the walk passed through or stopped at."""

    index: int
    answer: str | None  # "yes", "no", or None when the question has no check
    ends_here: bool  # True when the branch taken is the leaf


@dataclass(frozen=True)
class Leaf:
    index: int
    answer: str
    do: str
    screen: str | None
    label: str  # "Bạn đang ở đây"


@dataclass(frozen=True)
class TreeResult:
    highlighted: bool  # False when the tree is only a reference (for example no node chosen)
    steps: tuple[Step, ...] = field(default_factory=tuple)
    leaf: Leaf | None = None

    @property
    def path(self) -> list[tuple[int, str | None]]:
        return [(s.index, s.answer) for s in self.steps]


Trees = dict[str, list[Question]]


def _branch(raw: Any, where: str) -> Branch | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not raw.get("do"):
        raise DecisionTreeError(f"{where}: a branch needs a 'do' text")
    screen = raw.get("screen")
    return Branch(str(raw["do"]), None if screen is None else str(screen))


def _normalise_keys(raw: dict[Any, Any]) -> dict[str, Any]:
    """YAML 1.1 reads the bare keys yes/no as booleans; turn them back into text."""
    names = {True: "yes", False: "no"}
    return {names.get(k, k) if isinstance(k, bool) else str(k): v for k, v in raw.items()}


def parse_trees(data: Any) -> Trees:
    if not isinstance(data, dict):
        raise DecisionTreeError("decision tree file must be a mapping of tree name to question list")
    trees: Trees = {}
    for name, items in data.items():
        if not isinstance(items, list) or not items:
            raise DecisionTreeError(f"tree '{name}' must be a non-empty list of questions")
        questions: list[Question] = []
        for i, item in enumerate(items):
            where = f"{name}[{i}]"
            if not isinstance(item, dict):
                raise DecisionTreeError(f"{where}: a question must be a mapping")
            item = _normalise_keys(item)
            if not item.get("q"):
                raise DecisionTreeError(f"{where}: missing 'q'")
            check = item.get("check")
            if check is not None and check not in rules.CHECKS:
                raise DecisionTreeError(f"{where}: unknown check '{check}'")
            questions.append(
                Question(i, str(item["q"]), check, _branch(item.get("yes"), where + ".yes"),
                         _branch(item.get("no"), where + ".no"))
            )
        trees[str(name)] = questions
    return trees


def load_trees(path: Path | str | None = None) -> Trees:
    """Read and validate the tree file. Call again to reload."""
    target = Path(path) if path else DEFAULT_PATH
    try:
        with open(target, encoding="utf-8") as fh:
            return parse_trees(yaml.safe_load(fh))
    except OSError as exc:
        raise DecisionTreeError(f"cannot read {target}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise DecisionTreeError(f"{target} is not valid YAML: {exc}") from exc


class TreeStore:
    """Holds the loaded trees; ``reload()`` rereads the file (Settings > reload)."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self.trees: Trees = load_trees(self.path)

    def reload(self) -> Trees:
        self.trees = load_trees(self.path)
        return self.trees

    def evaluate(self, name: str, data: Any, ctx: rules.Context | None = None) -> TreeResult:
        return evaluate(self.trees[name], data, ctx)


def evaluate(
    questions: list[Question],
    data: rules.Analysis | dict[str, list[dict[str, Any]]],
    ctx: rules.Context | None = None,
) -> TreeResult:
    """Walk the questions and return the path that is true now and the leaf reached.

    If a check cannot be answered (for example a node check with no node selected) the
    tree is returned without highlight: a plain reference.
    """
    analysis = data if isinstance(data, rules.Analysis) else rules.Analysis(data, ctx)
    steps: list[Step] = []
    for question in questions:
        if question.check is None:
            steps.append(Step(question.index, None, False))
            continue
        answer = rules.CHECKS[question.check](analysis)
        if answer is None:
            return TreeResult(False)
        name = "yes" if answer else "no"
        branch = question.yes if answer else question.no
        if branch is not None:
            steps.append(Step(question.index, name, True))
            leaf = Leaf(question.index, name, branch.do, branch.screen, rules.TEXTS["tree_here"])
            return TreeResult(True, tuple(steps), leaf)
        steps.append(Step(question.index, name, False))
    return TreeResult(True, tuple(steps), None)
