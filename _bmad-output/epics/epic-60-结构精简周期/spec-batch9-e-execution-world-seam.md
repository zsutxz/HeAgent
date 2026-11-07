---
title: '批次 9 卡 E：执行世界 seam 统一（安全邻域，压轴）'
type: 'refactor'
created: '2026-11-07'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 执行世界双轨并存：`SandboxSession.run` 运行期读全局 runner slot（session.py:191）——runner 泄漏进 session 世界；shell handler session-first 优先级只活在代码里（shell.py:20-23 静默，docstring 还宣称只走 get_command_runner）；container 双 runner 并存仅运行期 WARNING+忽略（container.py:151-158）。

**Approach:** (a) runner 构造期参数化：`SandboxSession.__init__` keyword-only 必填收 runner、`run()` 杀全局读；`get_or_create_session` 透传；executor.py:410 在 bind 块内传 `self.sandbox_runner`（bind 块内构造 ⇒ 取值与现运行期恒同，行为等价）。(b) shell 优先级 docstring 显式声明（零运行时输出变化）。(c) `configure_command_runner` docstring 降级声明为测试缝；container 双 runner 转构造期显式判定（executor.sandbox_runner 优先，去 WARNING）。测试先行补三钉（解耦/优先级/构造判定）。

</frozen-after-approval>

## Implementation Notes

**调查结论（2026-11-07，HEAD 89ff596）：**

- 三现场：shell.py:20-23（session slot 先、runner 兜底、零告警；docstring :3-8 已失真）；session.py:189-213（:191 全局读 + isinstance DockerRunner 分型 cd-wrap：容器侧 `_docker_cwd` / 宿主侧 `self.cwd` 双轨 cwd 并行维护）；container.py:148-158（WARNING 逐字 "command_runner is set but executor.sandbox_runner is already %s; command_runner is ignored"，else 分支 :158 赋值）。
- slot API：RuntimeSlot（runtime.py:16-48）= 进程级 `_default`（configure/reset）+ ContextVar（bind/get）。slot 实例 process.py:312 / session.py:238；生产 bind 唯一点 executor.py:405（`bind_command_runner(self.sandbox_runner)`）+ :410 session 创建在其内 ⇒ 构造期捕获等价。生产读点仅 shell.py:20,23 + session.py:191。`configure_command_runner`（process.py:316）src 零生产调用（仅 __init__.py re-export）——已是事实测试缝。
- 测试触点：全部直接 import + with-bind，**零 monkeypatch 字符串**。必填签名波及：SandboxSession 单参构造 13 处（test_sandbox.py 1127-1353 系；test_sandbox_docker.py:601）+ get_or_create_session 调用（executor.py:410；test_engine_p0.py pop 链 :1348 清理不改签名）。其中 run() 依赖 bind 的 8 处需把 runner 挪进构造（:1170/:1185/:1229/:1239/:1247/:1293/:1338/:1353 + docker :602）。
- 测试钉现状：container WARNING 文案**零钉**；shell 优先级**零钉**；configure 兜底语义钉在 test_sandbox.py:890/896（docstring 降级不影响）；test_sandbox.py:788/:561-620/:1319-1352 handler 读点不受影响。
- 契约测试不涉：session.py 仅在 .heagent 字面量清单（contracts:626）与 sandbox click-free（:480-490），均与 runner slot 无关。
- docs 同步点：sandbox.md:45-47（session-first 流程措辞显式化）、:63（缝表 bind_command_runner 误写 contracts.py——实为 process.py:325，顺手修正）、:64；frame.md:472（FR-4 canonical 已declare「handler 优先走 session」，补构造期参数化半句）；shell.py docstring :3-8 重写。

**执行面（动面清单）：**
1. session.py：`__init__(workspace, *, runner)`（keyword-only 必填，`self._runner`）；`run()` :191 改 `self._runner`；`get_or_create_session(run_id, workspace, *, runner)` 透传；isinstance 分型逻辑原样（DockerRunner/WinJobBackend import 保留）。
2. executor.py:410 传 `runner=self.sandbox_runner`。
3. shell.py：docstring 重写（session-first 显式声明 + runner 兜底），代码零变化。
4. container.py:148-158：构造期显式判定——executor.sandbox_runner 优先、仅 command_runner 时赋值；删 WARNING；规则 docstring/注释成文。
5. process.py：configure_command_runner docstring 降级声明为测试缝（re-export 不动）。
6. 测试：13 处构造点补 runner 实参（静态类用 PassthroughRunner()/stub；docker 用其 fake）；新增三钉——①解耦钉（session 构造 runner A + 全局 bind B → run 用 A）②shell 优先级钉（session+runner 并存走 session）③container 判定钉（both→sandbox_runner 胜且无 WARNING；仅 command_runner→赋值）。
7. docs：sandbox.md 三处 + frame.md :472 半句。
8. 门禁（pytest 不带 --cov + ruff + format + mypy）→ 呈报制提交 → 台账行 → memory。
