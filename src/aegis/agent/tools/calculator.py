"""Calculator tool — a safe arithmetic expression evaluator.

Deliberately does NOT use `eval()`/`exec()`. The expression is parsed into an
AST and walked by hand, allowing only numeric literals, +-*/ //, %, **, unary
+/-, and a small allowlist of `math` functions called by name. Anything else
(attribute access, name lookup outside the allowlist, comprehensions,
lambdas, imports...) is rejected before any computation happens — there is
no code path that can execute arbitrary Python from a tool argument.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from pydantic import BaseModel, Field

from aegis.agent.tools.base import Tool, ToolExecutionError

_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCS: dict[str, Any] = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "pow": pow,
    "log": math.log,
    "log10": math.log10,
    "floor": math.floor,
    "ceil": math.ceil,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ToolExecutionError("only numeric constants are allowed")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            func_name = getattr(node.func, "id", "<unknown>")
            raise ToolExecutionError(f"function not allowed: {func_name}")
        if node.keywords:
            raise ToolExecutionError("keyword arguments are not allowed")
        return _FUNCS[node.func.id](*(_eval_node(a) for a in node.args))
    raise ToolExecutionError(f"disallowed expression element: {type(node).__name__}")


class CalculatorArgs(BaseModel):
    expression: str = Field(
        ..., description="Arithmetic expression, e.g. '12 * (7 + 1)' or 'sqrt(2)'"
    )


class CalculatorTool(Tool[CalculatorArgs]):
    name = "calculator"
    description = (
        "Evaluate an arithmetic expression. Supports + - * / // % ** and the "
        "functions sqrt, abs, round, min, max, pow, log, log10, floor, ceil."
    )
    args_model = CalculatorArgs
    timeout_s = 2.0

    async def run(self, arguments: CalculatorArgs) -> float:
        try:
            tree = ast.parse(arguments.expression, mode="eval")
        except SyntaxError as exc:
            raise ToolExecutionError(f"invalid expression syntax: {exc}") from exc
        return _eval_node(tree.body)
