from __future__ import annotations

import ast
from pathlib import Path

from runtime_evaluation import RuntimeEvaluationMixin
from structural_reasoning_gate import StructuralProofRequest, StructuralReasoningGate
from zoran_runtime import ZoranRuntime


ROOT = Path(__file__).resolve().parent
SPLIT_MODULES = (
    "structural_reasoning_gate",
    "structural_reasoning_shared",
    "structural_numeric_rules",
    "structural_factoid_rules",
)


def _local_imports(module: str) -> set[str]:
    tree = ast.parse((ROOT / f"{module}.py").read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in SPLIT_MODULES:
            result.add(node.module)
        elif isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names if alias.name in SPLIT_MODULES)
    return result


def _branch_count(node: ast.AST) -> int:
    branches = (ast.If, ast.For, ast.While, ast.Try, ast.BoolOp, ast.Match)
    return sum(isinstance(child, branches) for child in ast.walk(node))


def test_central_facades_stay_bounded() -> None:
    structural_lines = (ROOT / "structural_reasoning_gate.py").read_text(encoding="utf-8").splitlines()
    runtime_lines = (ROOT / "zoran_runtime.py").read_text(encoding="utf-8").splitlines()
    assert len(structural_lines) <= 1500
    assert len(runtime_lines) <= 250


def test_structural_split_has_no_import_cycle() -> None:
    edges = {module: _local_imports(module) for module in SPLIT_MODULES}

    def visit(module: str, stack: tuple[str, ...]) -> None:
        assert module not in stack
        for dependency in edges[module]:
            visit(dependency, stack + (module,))

    for module in SPLIT_MODULES:
        visit(module, ())


def test_runtime_evaluation_stages_stay_bounded() -> None:
    tree = ast.parse((ROOT / "runtime_evaluation.py").read_text(encoding="utf-8"))
    mixin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RuntimeEvaluationMixin")
    methods = [node for node in mixin.body if isinstance(node, ast.FunctionDef)]
    assert max(_branch_count(method) for method in methods) <= 25


def test_public_facades_remain_callable() -> None:
    assert issubclass(ZoranRuntime, RuntimeEvaluationMixin)
    result = StructuralReasoningGate().evaluate(
        StructuralProofRequest("There are 8 families and 10 households.", "How many more households than families?", "2")
    )
    assert result.status.value == "PROVED"
