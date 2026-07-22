import pytest

from aegis.agent.tools.base import ToolExecutionError
from aegis.agent.tools.calculator import CalculatorArgs, CalculatorTool


async def test_basic_arithmetic() -> None:
    tool = CalculatorTool()
    result = await tool.run(CalculatorArgs(expression="12 * (7 + 1)"))
    assert result == 96


async def test_functions_allowlist() -> None:
    tool = CalculatorTool()
    assert await tool.run(CalculatorArgs(expression="sqrt(16)")) == 4.0
    assert await tool.run(CalculatorArgs(expression="max(3, 9, 1)")) == 9


async def test_rejects_name_lookup() -> None:
    tool = CalculatorTool()
    with pytest.raises(ToolExecutionError):
        await tool.run(CalculatorArgs(expression="__import__('os').system('echo pwned')"))


async def test_rejects_disallowed_function() -> None:
    tool = CalculatorTool()
    with pytest.raises(ToolExecutionError):
        await tool.run(CalculatorArgs(expression="open('/etc/passwd')"))


async def test_rejects_invalid_syntax() -> None:
    tool = CalculatorTool()
    with pytest.raises(ToolExecutionError):
        await tool.run(CalculatorArgs(expression="1 + "))


async def test_rejects_non_numeric_constant() -> None:
    tool = CalculatorTool()
    with pytest.raises(ToolExecutionError):
        await tool.run(CalculatorArgs(expression="'a' + 'b'"))
