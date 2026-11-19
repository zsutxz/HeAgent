"""Story 66.5：大型 LLM SDK 延迟导入的回归判据。

判据一律在**干净子进程**里读 ``sys.modules``——同进程内的 import 缓存无法证明「未导入」。
冷启动收益用「比两个 SDK 的导入耗时」度量（Epic 66 的 Done when 是「冷启动降低 >20%」）：
绝对耗时随机器漂移，比值不漂——省掉 SDK 就该比装上 SDK 明显更快。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 子进程里跑断言脚本：断言失败即非零退出，stderr 带 AssertionError 原文。
_NO_LEAKED_SDKS = """
import sys

for sdk in ("openai", "anthropic"):
    assert sdk not in sys.modules, f"{sdk} imported eagerly"
"""


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv 是固定字面量 + 当前解释器路径，无外部输入
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_import_heagent_does_not_import_llm_sdks() -> None:
    """``import heagent`` 不得把 openai / anthropic 拉进 ``sys.modules``。"""
    result = _run("import heagent\n" + _NO_LEAKED_SDKS)
    assert result.returncode == 0, result.stderr


def test_providers_package_lazy_exports_do_not_import_sdks() -> None:
    """``from heagent.providers import OpenAIProvider`` 取到类，但 SDK 仍不落地。"""
    result = _run(
        "from heagent.providers import AnthropicProvider, OpenAIProvider\n"
        "assert OpenAIProvider.__name__ == 'OpenAIProvider'\n"
        "assert AnthropicProvider.__name__ == 'AnthropicProvider'\n" + _NO_LEAKED_SDKS
    )
    assert result.returncode == 0, result.stderr


def test_providers_package_lazy_export_surface() -> None:
    """包级 ``__getattr__`` 契约：``__all__`` 里的符号可解析，未知符号抛 AttributeError。"""
    import heagent.providers as providers
    from heagent.providers.openai import OpenAIProvider

    assert providers.OpenAIProvider is OpenAIProvider
    with pytest.raises(AttributeError, match="NotAProvider"):
        _ = providers.NotAProvider


def test_constructing_openai_provider_imports_sdk() -> None:
    """构造 provider 才导入 SDK（延迟导入不是「永不导入」）。"""
    result = _run(
        "import sys\n"
        "from heagent.providers import OpenAIProvider\n"
        "assert 'openai' not in sys.modules\n"
        "OpenAIProvider(api_key='x', model='m')\n"
        "assert 'openai' in sys.modules, 'openai not imported on construction'\n"
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 冷启动收益（Epic 66 Done when：懒加载使冷启动降低 >20%）
# ---------------------------------------------------------------------------

#: 冷启动对比的次数：取最小值（首轮受页缓存/前台噪声影响）。SDK 侧单次就上秒级，故少跑。
_HEAGENT_COLD_RUNS = 3
_SDK_COLD_RUNS = 2

#: 允许的耗时比：``import heagent`` 必须比「装上两个 SDK」快至少 20%。
_MAX_RATIO = 0.8


def _cold_seconds(code: str, *, runs: int) -> float:
    """在干净子进程里跑 ``runs`` 次 ``code``，返回墙钟耗时的最小值。"""
    samples: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        result = _run(code)
        samples.append(time.perf_counter() - started)
        assert result.returncode == 0, result.stderr
    return min(samples)


@pytest.mark.benchmark
def test_cold_import_is_at_least_twenty_percent_cheaper_than_loading_sdks() -> None:
    """``import heagent`` 的冷启动必须比「python -c 'import openai, anthropic'」快 >20%。

    判据是**比值**：延迟导入的价值就是「不付 SDK 的导入代价」，省不到 20% 说明有东西在
    启动期把 SDK 拉回来了（或引入了等量的重导入）。绝对毫秒数不参与断言。
    """
    for sdk in ("openai", "anthropic"):
        if importlib.util.find_spec(sdk) is None:  # pragma: no cover - 依赖缺失时无对比基准
            pytest.skip(f"{sdk} 未安装，无冷启动对比基准")

    heagent_cost = _cold_seconds("import heagent", runs=_HEAGENT_COLD_RUNS)
    sdk_cost = _cold_seconds("import openai, anthropic", runs=_SDK_COLD_RUNS)
    assert heagent_cost < _MAX_RATIO * sdk_cost, (
        f"冷启动未省下 20%：import heagent {heagent_cost * 1000:.0f}ms vs "
        f"import openai,anthropic {sdk_cost * 1000:.0f}ms"
    )
