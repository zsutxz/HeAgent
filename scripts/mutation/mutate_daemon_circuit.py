"""daemon 心跳/熔断的**负向变异验证**（2026-11-02 三次修订：重试 / 半开复探 / 分档 / 折叠必须被守住）。

背景：
- 2026-11-02 11:10 误判形态——`docker version` 单次 5s 超时即判死并熔断 120s，而同一分钟内
  `docker run` 只需 567ms；熔断期里 daemon 早已恢复，后续命令仍被判「未执行」。
- 2026-11-02 13:58 误判形态——9 分钟无 docker 活动后同一批三条并行 shell 的探针各耗尽 5s×2
  预算、判死并熔断 120s，2 分钟后同一 daemon 的单条命令只 610ms；模型据此劝用户重启 Desktop。

修复后的不变量（每条都要有判据压住）：
① 探测多次（递增预算）都失败才算死；② 探针超时（慢）**不**否决命令——只有硬失败才进熔断；
③ 窗口内心跳过期即半开复探，恢复或仅超时都放行、硬失败才顺延；④ 同批并发只付一次探针
（single-flight）；⑤ CLI 明确报错立即判死，不耗尽剩余超时预算。
本脚本把 `tools/sandbox/docker.py` 复制到 `.heagent/tmp/mut-circuit/` 下逐条回退这些不变量，
要求**每条变异都红**（否则判据不足以护住该不变量）。

用法（在仓库根；不需要 docker daemon）：

    python scripts/mutation/mutate_daemon_circuit.py

输出：每条变异一行 ``RED/GREEN`` + 失败用例数；任一条 GREEN ⇒ 退出码 1。

**入库**（而非 `.heagent/tmp/`）：判据强度结论必须能独立复核；它不进测试套件（是元验证）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 本文件在 scripts/mutation/ 下
MUT_ROOT = ROOT / ".heagent" / "tmp" / "mut-circuit"  # 一次性产物（gitignore）
TARGET_REL = "src/heagent/tools/sandbox/docker.py"
TEST_FILE = "tests/test_sandbox_docker.py"

# (id, 说明, [(原文, 替换), ...])；每条原文必须**恰好出现一次**，否则脚本报错退出。
MUTATIONS: list[tuple[str, str, list[tuple[str, str]]]] = [
    (
        "M1",
        "探测退化回单次（一次超时就判死）",
        [
            (
                "_HEALTH_PROBE_TIMEOUTS: tuple[float, ...] = (3.0, 8.0)",
                "_HEALTH_PROBE_TIMEOUTS: tuple[float, ...] = (3.0,)",
            )
        ],
    ),
    (
        "M2",
        "熔断窗内不半开复探（退回「拒满整窗」旧行为）",
        [
            (
                "        reason = await self._probe_daemon()\n"
                "        if reason == _PROBE_OK:\n"
                '            logger.info("docker daemon answered again; container sandbox resumed")\n'
                "            self._degraded_until = 0.0\n"
                "            return None\n",
                "        return self._paused_result()\n",
            )
        ],
    ),
    (
        "M3",
        "窗内无视心跳 TTL（每条命令都付探针）",
        [
            (
                "        if time.monotonic() - self._last_health_probe < _HEALTH_PROBE_TTL_SECONDS:\n"
                "            return self._paused_result()\n",
                "",
            )
        ],
    ),
    (
        "M4",
        "半开复探失败不顺延窗口",
        [
            (
                "        self._pause(reason)\n        return self._paused_result()\n",
                "",
            )
        ],
    ),
    (
        "M5",
        "慢不否决退化：探针超时也暂停（命令被跳过）",
        [
            (
                "        if failure is not None and failure != _PROBE_TIMEOUT:\n",
                "        if failure is not None:\n",
            )
        ],
    ),
    (
        "M6",
        "去掉探测 single-flight（同批并发各探一次）",
        [
            (
                "        async with self._probe_lock:\n"
                "            if time.monotonic() - self._last_health_probe < _HEALTH_PROBE_TTL_SECONDS:\n"
                "                return self._last_probe_reason\n",
                "        if True:\n",
            )
        ],
    ),
    (
        "M7",
        "明确报错不短路（耗尽剩余超时预算才判死）",
        [
            (
                "            if probe.returncode == 0:\n"
                "                return _PROBE_OK\n"
                "            return _PROBE_UNAVAILABLE\n",
                "            if probe.returncode == 0:\n"
                "                return _PROBE_OK\n"
                "            last_reason = _PROBE_UNAVAILABLE\n"
                "            continue\n",
            )
        ],
    ),
    (
        "M8",
        "半开复探超时也续窗（恢复期被无限延长）",
        [
            (
                "        if reason == _PROBE_TIMEOUT:\n"
                "            logger.warning(\n"
                '                "docker daemon probe timed out after the hard failure; sandbox resumed and running this "\n'
                '                "command anyway (slow CLI, not necessarily dead)"\n'
                "            )\n"
                "            self._degraded_until = 0.0\n"
                "            return None\n",
                "        if reason == _PROBE_TIMEOUT:\n"
                "            self._pause(reason)\n"
                "            return self._paused_result()\n",
            )
        ],
    ),
]


def _prepare() -> Path:
    if MUT_ROOT.exists():
        shutil.rmtree(MUT_ROOT)
    shutil.copytree(ROOT / "src", MUT_ROOT / "src")
    shutil.copytree(ROOT / "tests", MUT_ROOT / "tests", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "ruff.toml", ".env.example"):
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, MUT_ROOT / name)
    return MUT_ROOT / TARGET_REL


def _run_tests() -> tuple[int, int]:
    """跑单测面；返回 ``(退出码, 失败用例数)``。"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_FILE, "-q", "-p", "no:cacheprovider"],
        cwd=MUT_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        env={"PYTHONPATH": str(MUT_ROOT / "src")},
    )
    failed = 0
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(("FAILED ", "ERROR ")):
            failed += 1
    return result.returncode, failed


def main() -> int:
    target = _prepare()
    pristine = target.read_text(encoding="utf-8")

    baseline_code, baseline_failed = _run_tests()
    print(f"[baseline] exit={baseline_code} failed={baseline_failed}")
    if baseline_code != 0:
        print("基线本身就红：先修基线，变异结论无意义。")
        return 2

    survived: list[str] = []
    for ident, description, patches in MUTATIONS:
        mutated = pristine
        for old, new in patches:
            count = mutated.count(old)
            if count != 1:
                print(f"[{ident}] 变异锚点出现 {count} 次（应为 1）：{description}")
                return 2
            mutated = mutated.replace(old, new)
        target.write_text(mutated, encoding="utf-8")
        try:
            code, failed = _run_tests()
        finally:
            target.write_text(pristine, encoding="utf-8")
        status = "RED" if code != 0 else "GREEN"
        print(f"[{ident}] {status} failed={failed}  {description}")
        if code == 0:
            survived.append(f"{ident} {description}")

    print("----")
    if survived:
        print(f"存活变异 {len(survived)}/{len(MUTATIONS)}（判据不足）：")
        for item in survived:
            print(f"  - {item}")
        return 1
    print(f"全部变红：{len(MUTATIONS)}/{len(MUTATIONS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
