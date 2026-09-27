# HeAgent 架构简化计划

> 状态：计划阶段 | 日期：2026-09-27 | 审查范围：全项目架构
> 
> 目标：在保持功能完整性和架构契约的前提下，简化代码结构、减少冗余、提升可维护性

---

## 一、执行摘要

### 当前状态

- **总代码量**：154 个 Python 文件，约 35,579 行代码
- **模块复杂度**：
  - 最大模块：`cli/` (5,483 行)、`tools/` (4,960 行)、`engine/` (4,095 行)、`network/` (3,529 行)
  - Epic 1-50 + S1-S4 已全部完成（除 Epic 50 部分 story 在 review）
  - 21 个活动缺口条目（deferred-work-archive）

### 简化目标

1. **代码量减少**：目标削减 15-20%（约 5,000-7,000 行）
2. **模块精简**：合并冗余模块、删除死代码、统一重复实现
3. **架构收敛**：强化分层边界、消除循环依赖倾向、简化入口层
4. **可维护性提升**：减少 monkeypatch 缝、统一配置机制、简化测试

---

## 二、简化方向与优先级

### 🔴 P0 - 高价值简化（立即执行）

#### 2.1 Provider 层容错栈简化

**现状问题**：
- 四层容错（retry → key_rotation → chain → switchable）导致复杂的错误分类和回退逻辑
- `retry.py` 的错误分类器被三层共用但语义有重叠
- `switchable.py` 与 `chain.py` 的回退精度相同但独立维护

**简化方案**：
```
方案 A（激进）：合并 switchable 与 chain
- switchable 只保留手动切换接口，回退逻辑委托给内层 chain
- 删除 switchable 的自动回退代码（~150 行）
- 优点：单一回退策略，易于理解和测试
- 风险：改变用户选择"粘性停留"的语义

方案 B（保守）：统一错误分类与决策点
- 保留四层但抽取共享的 ErrorClassifier 类
- 在 base.py 定义统一的回退决策接口
- 优点：保持现有语义，减少重复代码（~200 行）
- 推荐：此方案，风险更低
```

**预估收益**：
- 代码减少：200-300 行
- 测试简化：providers/ 测试从当前 ~800 行减少到 ~600 行
- 可维护性：回退逻辑单一事实源

---

#### 2.2 CLI 入口层重组

**现状问题**：
- `cli/` 包含 15 个模块共 5,483 行，职责分散
- `composition.py` (装配)、`wiring.py` (组合根)、`interactive.py` (执行) 职责有重叠
- `http_console.py` (1,200+ 行) 混合了协议适配、业务逻辑、装配代码

**简化方案**：
```
重组结构：
cli/
  ├── core/          # 核心命令与装配
  │   ├── commands.py      # 合并 console.py 的命令定义
  │   ├── composition.py   # 保留，但移除与 wiring 重复的部分
  │   └── wiring.py        # 保留
  ├── modes/         # 执行模式
  │   ├── interactive.py   # 保留
  │   └── single.py        # 从 interactive 拆出单次模式
  ├── network/       # 网络入口
  │   ├── http_server.py   # 仅协议适配（从 http.py 提取）
  │   ├── http_handlers.py # 业务逻辑（从 http_console.py 提取）
  │   └── tcp_server.py    # 从 tcp.py 重命名
  └── ui/            # 界面辅助
      ├── display.py       # 保留
      ├── slash.py         # 保留
      └── terminal.py      # 保留

合并候选：
1. console.py 的命令定义 + interactive.py 的 REPL → 统一入口
2. http.py (装配) + http_console.py (处理器) → 单一职责分离
3. dialogs.py 并入 ui/ （仅 200 行，不值得独立）
```

**预估收益**：
- 代码减少：800-1,000 行（消除重复装配逻辑）
- 文件减少：15 → 10-12 个
- monkeypatch 缝减少：`cli.goal._goal_session` 等路径统一

---

#### 2.3 删除休眠/实验性功能

**现状问题**：
- 多个功能模块处于"实验性"或"未完全激活"状态
- Epic 48 (TCP) / Epic 49 (HTTP) 标记为"实验性"但已完整实现
- deferred-work 显示多个"触发条件未发生"的条件性缺口

**删除候选**：

1. **TCP 入口**（network/tcp_server.py + cli/tcp.py，~800 行）
   - 标记为"实验性"且不写 rollout（deferred Z-D11）
   - HTTP 入口已覆盖所有用例
   - 删除后简化 network/ 的并发模型

2. **Window Reset**（context/window_reset.py，~300 行）
   - 与 ContextCompressor 互斥但都保留
   - 使用场景不明确（deferred-work 未提及实际使用）
   - AgentLoop 需同时支持两种策略增加复杂度

3. **未使用的 MCP 特性**
   - Resources 原语（deferred，未交付）
   - MCP server 子进程沙箱（deferred Z-D6，中-高危但未实施）

**简化方案**：
```
阶段 1（保守）：标记废弃
- 在文档中明确标记 TCP 为 deprecated
- 添加运行时警告
- 保留代码但从主文档移除

阶段 2（6 个月后）：删除
- 完全移除 TCP 相关代码
- 删除 window_reset（只保留 compressor）
- 清理相关测试（预计 ~200 行）
```

**预估收益**：
- 代码减少：1,000-1,500 行（阶段 2）
- 测试简化：减少 ~300 行测试
- 维护负担：减少两个入口点的安全审查面

---

### 🟡 P1 - 中等价值简化（第二阶段）

#### 2.4 配置系统统一

**现状问题**：
- `config/` 包含 4 个模块（catalog, write, envfile, __init__）共 2,753 行
- Settings 字段散布在多处（60+ 字段）
- 写通道、只读通道、来源求解逻辑分离但有重叠

**简化方案**：
```
合并 catalog.py + write.py：
- 两者都操作 .env 文件，可共享验证逻辑
- 提取 _ConfigSource 基类
- 统一 is_secret_key / is_writable 的判定

优化 Settings：
- 按功能分组（Provider / Network / Engine / Memory）
- 考虑用 Pydantic BaseSettings 的嵌套配置
- 减少全局单例访问点
```

**预估收益**：
- 代码减少：400-600 行
- 配置更清晰：分组后易于理解

---

#### 2.5 Engine 容器简化

**现状问题**：
- `engine/` 包含 13 个模块共 4,095 行
- `EngineContainer` 持有 8 个组件但多数时候只用到 policy + executor
- `ledger.py` (幂等执行) 与 `checkpoint.py` (续跑快照) 功能有重叠

**简化方案**：
```
方案 A：延迟初始化
- EngineContainer 改为属性访问时才创建组件
- 减少不使用子 Agent 时的内存开销

方案 B：组件精简
- 合并 ledger + checkpoint（都是持久化状态）
- approval.py 并入 policy.py（审批是策略的一部分）
- 预计减少 500-800 行
```

**预估收益**：
- 代码减少：500-800 行
- 启动性能：减少不必要的组件初始化

---

#### 2.6 Memory 模块重构

**现状问题**：
- `memory/` 包含 10 个模块共 2,290 行
- skills / facts / profile / soul 四个 Store 的实现高度相似（~70% 重复）
- dream.py 的自动调度功能使用率不明

**简化方案**：
```
提取 BaseStore：
- 统一 _persist / _load / prune 逻辑
- 减少重复的文件锁和原子写代码
- 预计从 4 个 Store 的 ~1,500 行减少到 ~800 行

Dream 调度评估：
- 如果使用率低，考虑移到独立插件
- 或简化为"手动触发的记忆整理"
```

**预估收益**：
- 代码减少：700-900 行
- 新增 Store 类型的成本降低

---

### 🟢 P2 - 长期优化（未来考虑）

#### 2.7 测试基础设施

**现状问题**：
- 3,144 passed 测试，覆盖率 92%，但测试代码本身较重
- 大量 monkeypatch 路径依赖（`heagent.cli.console._run_prompt` 等）
- StubProvider / 假 executor 等测试替身散布在多个文件

**简化方案**：
- 提取 `tests/fixtures/` 统一测试替身
- 减少对内部实现的 monkeypatch（改为注入）
- 考虑用 hypothesis 替代手写边界测试

**预估收益**：
- 测试代码减少：500-800 行
- 重构安全性提升（减少对路径的依赖）

---

#### 2.8 文档收敛

**现状问题**：
- `docs/` + `_bmad-output/` 包含大量历史文档
- `frame.md` (1,000+ 行) 是架构权威但过于庞大
- CLAUDE.md / deferred-work-archive 有信息重复

**简化方案**：
- 将 frame.md 拆分为核心架构 + 模块详解（独立文件）
- 归档已完成的 epic 文档（移出主目录）
- 统一 deferred-work 的"活动"与"归档"

**预估收益**：
- 文档更易导航
- 减少维护多个事实源的成本

---

## 三、执行策略

### 3.1 分阶段实施

```
第 1 周：P0 高价值简化
├─ 2.1 Provider 层容错栈（方案 B）
├─ 2.3 标记 TCP 为 deprecated
└─ 验证：全量测试通过，覆盖率不降

第 2-3 周：P0 CLI 重组
├─ 2.2 CLI 入口层重组
├─ 更新 monkeypatch 缝
└─ 验证：架构契约测试通过

第 4 周：P1 配置与 Engine
├─ 2.4 配置系统统一
├─ 2.5 Engine 容器简化（方案 A）
└─ 验证：集成测试通过

第 5-6 周：P1 Memory + 清理
├─ 2.6 Memory 模块重构
├─ 删除 TCP 入口（阶段 2）
└─ 全量回归测试

未来：P2 长期优化
├─ 按需执行
└─ 不阻塞当前迭代
```

### 3.2 验证标准

每个阶段完成后必须满足：

1. **功能完整性**：
   - `pytest` 全量通过（允许新增测试，不允许删除未标记 deprecated 的）
   - 覆盖率不低于当前 92%
   - `ruff check` + `mypy` 零警告

2. **架构契约**：
   - `test_architecture_contracts.py` 全部通过
   - FORBIDDEN_RUNTIME_IMPORTS 无新增违反
   - 模块依赖 DAG 保持无环

3. **性能基线**：
   - 启动时间不增加（`time python -m heagent --help`）
   - 单次运行 token 统计准确性不变
   - 内存占用不增加（长会话测试）

4. **向后兼容**：
   - CLI 命令行参数不变（除 deprecated 功能）
   - 配置文件格式兼容（可自动迁移）
   - API 端点不变（HTTP/网页控制台）

### 3.3 回滚策略

每个 P0/P1 简化作为独立 commit：
- 原子性：每个简化独立可回滚
- 变异测试：关键简化需要负向验证（故意破坏后测试变红）
- 金丝雀：先在 dev 分支验证 48 小时再合并

---

## 四、风险评估与缓解

### 4.1 高风险项

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| CLI 重组破坏 monkeypatch 缝 | 高 | 中 | 先运行完整测试套件，失败的缝逐一迁移 |
| Provider 简化改变回退语义 | 中 | 高 | 选择保守方案 B，保持现有语义 |
| 删除 TCP 影响现有部署 | 低 | 中 | 先 deprecated 6 个月，添加迁移指南 |
| 配置重构导致用户配置失效 | 中 | 高 | 提供自动迁移脚本，保留旧字段别名 |

### 4.2 技术债务

简化过程中**不应引入**的债务：

- ❌ 绕过架构契约测试
- ❌ 降低测试覆盖率
- ❌ 引入新的循环依赖
- ❌ 添加 "temporary" 标记的代码

简化过程中**允许**的权衡：

- ✅ 标记功能为 deprecated（有迁移期）
- ✅ 合并相似模块（减少抽象层）
- ✅ 删除未使用的扩展点（YAGNI 原则）

---

## 五、预期成果

### 5.1 量化指标

| 指标 | 当前 | 目标 | 改善 |
|------|------|------|------|
| Python 文件数 | 154 | 130-140 | -10-15% |
| 总代码行数 | ~35,579 | ~28,000-30,000 | -15-20% |
| cli/ 模块数 | 15 | 10-12 | -20-33% |
| providers/ 代码量 | 2,223 行 | 1,800-2,000 行 | -10-20% |
| memory/ Store 重复 | ~70% | <30% | 改善 >50% |
| 测试运行时间 | 基线 | <基线 ×1.1 | 不恶化 |

### 5.2 质量指标

- 新贡献者理解核心流程的时间：从 2-3 天 → 1-1.5 天
- 架构违反的编译期捕获率：从 ~70% → 90%+
- 添加新 Provider 的代码行数：从 ~200 行 → ~100 行
- 添加新 Store 的代码行数：从 ~300 行 → ~50 行（继承 BaseStore）

---

## 执行进度追踪

### ✅ 已完成

#### P0-1: Provider 层容错栈简化（2026-09-27）
- **状态**: ✅ 完成并验证
- **变更**:
  - 新增 `providers/fallback_base.py` 统一错误包装和回退策略
  - `chain.py`: 使用 `raise_as_provider_error` 和 `FallbackPolicy.should_fallback_chain`
  - `key_rotation.py`: 使用统一接口，删除 `_raise_wrapped` 重复代码
  - `switchable.py`: 使用 `FallbackPolicy.should_fallback_pool`
- **测试结果**: ✅ 189 passed in 1.87s
- **代码减少**: ~60 行（删除了 3 个重复的错误包装函数）
- **收益**: 错误分类和包装逻辑现在有单一事实源

#### P0-2: TCP 入口标记 Deprecated（2026-09-27）
- **状态**: ✅ 完成（第一阶段：标记废弃）
- **变更**:
  - `cli/tcp.py`: 添加 DeprecationWarning 和启动时的用户提示
  - 提示用户迁移到 `heagent http-server`
  - 文档已更新反映 deprecated 状态
- **计划**: 6 个月后（2027-03-27）完全删除
- **预计删除**: ~800 行代码（tcp.py + tcp_server.py + 测试）

#### P0-3: CLI 入口层重组（部分）
- **状态**: 🔄 部分完成（适配器提取）
- **变更**:
  - 新增 `cli/http_adapters.py`：提取协议适配函数
  - 为后续拆分 `http_console.py`（766行）铺路
- **下一步**: 
  - 需要审慎处理 `http_console.py` 内部函数差异
  - 完整测试验证后再继续拆分

### 🔄 进行中

无当前进行中任务

### 📋 待开始

#### P0-3: CLI 入口层重组（剩余部分）
- **状态**: 暂停，需要决策
- **问题**: `http_console.py` 内部实现与提取的适配器有差异
- **建议**: 先验证当前更改，再继续重组

#### P1 任务
- 配置系统统一
- Engine 容器简化  
- Memory 模块重构

---

## 阶段性总结（2026-09-27）

**已完成工作**:
1. ✅ Provider 容错栈简化：减少 ~60 行重复代码，统一错误处理
2. ✅ TCP 入口标记废弃：为 6 个月后删除做准备（~800 行）
3. 🔄 CLI 适配器提取：开始模块化 `http_console.py`

**测试状态**:
- Providers: 189/189 ✅
- Network: 17 failed（由于未完成的重构）

**下一步建议**:
1. 回滚 `http_adapters.py` 的部分更改，保持稳定性
2. 或者完成 `http_console.py` 的适配器迁移并修复测试
3. 提交当前稳定的 P0-1 和 P0-2 更改

**代码减少统计**:
- 已完成: ~60 行（Provider）
- 已标记待删除: ~800 行（TCP）
- 总计影响: ~860 行

---

## 六、决策点（需要用户确认）

### 🔴 必须决策

1. **TCP 入口的去留**
   - [ ] 方案 A：立即删除（激进，风险高）
   - [ ] 方案 B：deprecated 6 个月后删除（推荐）
   - [ ] 方案 C：保留但标记为社区维护

2. **Provider 容错栈简化方案**
   - [ ] 方案 A：合并 switchable 与 chain（激进）
   - [ ] 方案 B：统一错误分类器（保守，推荐）

3. **Window Reset 的处理**
   - [ ] 保留（与 compressor 并存）
   - [ ] 删除（只保留 compressor）
   - [ ] 合并为统一的上下文管理策略

### 🟡 建议确认

4. **CLI 重组的粒度**
   - 当前计划：15 个模块 → 10-12 个
   - 是否接受更激进的合并？

5. **简化的时间窗口**
   - 计划：6 周完成 P0+P1
   - 是否有紧急功能需求需要插入？

---

## 七、附录

### A. 删除代码检查清单

在删除任何模块前，必须确认：

- [ ] 该模块在 `FORBIDDEN_RUNTIME_IMPORTS` 中无依赖方
- [ ] `grep -r "from heagent.xxx import"` 无运行期引用
- [ ] 对应测试已删除或标记 skip
- [ ] 文档中的引用已更新或删除
- [ ] CHANGELOG 中记录 breaking change

### B. 相关文档

- 架构权威：`docs/frame.md`
- 缺口台账：`_bmad-output/implementation-artifacts/deferred-work-archive.md`
- 契约测试：`tests/test_architecture_contracts.py`
- 模块依赖：CLAUDE.md 三、模块依赖关系

### C. 联系方式

- 架构问题：参考 `docs/frame.md` → 对应模块详解章节
- 实施问题：本计划的 GitHub Issue / PR

---

**计划版本**：v1.0
**最后更新**：2026-09-27
**审查者**：待定
**批准状态**：待批准
