"""Clock and calculator."""

import ast
import math
import operator
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pocketagent.tools import tool


@tool
def get_current_time(timezone: str = "") -> str:
    """Get the current date and time.

    Args:
        timezone: optional IANA time zone such as "Europe/Istanbul" or "America/New_York"
    """
    if timezone:
        try:
            now = datetime.now(ZoneInfo(timezone))
        except (ZoneInfoNotFoundError, ValueError):
            return f"Unknown time zone '{timezone}'."
    else:
        now = datetime.now().astimezone()
    return now.strftime("%A %d %B %Y, %H:%M (%Z, UTC%z)")


_OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
              ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCTIONS = {name: getattr(math, name) for name in
              ("sqrt", "sin", "cos", "tan", "log", "log10", "exp", "floor", "ceil", "radians", "degrees")}
_FUNCTIONS.update({"abs": abs, "round": round, "min": min, "max": max})
_CONSTANTS = {"pi": math.pi, "e": math.e}


def _evaluate(node):
    """Evaluate only arithmetic: no names, attributes or imports (unlike eval)."""
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return _OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPERATORS:
        return _OPERATORS[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
        return _FUNCTIONS[node.func.id](*[_evaluate(arg) for arg in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    raise ValueError("only numbers, + - * / // % **, parentheses and basic math functions are allowed")


@tool
def calculate(expression: str) -> str:
    """Calculate a math expression exactly. Use this instead of doing arithmetic in your head.

    Args:
        expression: for example "(1250 * 0.18) + 40" or "sqrt(2) * pi"
    """
    try:
        result = _evaluate(ast.parse(expression.replace("^", "**"), mode="eval"))
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError) as error:
        return f"Cannot calculate '{expression}': {error}"
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)
