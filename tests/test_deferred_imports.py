"""Story 66.5：大型 LLM SDK 延迟导入的回归判据。

判据一律在**干净子进程**里读 ``sys.modules``——同进程内的 import 缓存无法证明「未导入」。
"""

from __future__ import annotations

import subprocess
import sys
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
