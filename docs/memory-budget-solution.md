# 内存注入预算解决方案

## 问题描述

**现象**：
```
WARNING [heagent.agent.system_prompt] Memory injection exceeds MEMORY_INJECT_MAX_BYTES: 29 of 128 fact(s) omitted (budget=49152 bytes)
```

**原因**：
- MEMORY.md 采用 append-only 策略，条目持续增长
- 原默认预算 49152 字节（48 KB）不足以容纳 131 条事实（78290 字节）
- 导致 29 条最新事实被省略，影响记忆连续性

## 解决方案

采用**三层防御机制**：扩容 + 自动清理 + 手动整理

### 1. 扩大默认预算（立即缓解）

**改动**：`src/heagent/config/__init__.py`
- 默认预算从 49152 字节扩大到 **98304 字节（96 KB）**
- 约为当前使用量的 2 倍，提供充足余量

**配置参数**：
```bash
# .env 文件中可调整
MEMORY_INJECT_MAX_BYTES=98304  # 默认 96 KB，0=不限制
```

### 2. 自动归档机制（长期解决）

**新增模块**：`src/heagent/memory/auto_archive.py`

**工作原理**：
1. CLI 启动时自动检查 MEMORY.md
2. 识别超过指定天数的旧事实条目（默认 90 天）
3. 保留文件头部的前 20 条（核心约定）
4. 将旧条目归档到 `.heagent/memory/archive/<YYYY-MM>.md`
5. 更新 MEMORY.md，只保留核心约定和近期条目

**配置参数**：
```bash
# .env 文件中可调整
MEMORY_AUTO_ARCHIVE_DAYS=90           # 超过此天数的条目自动归档，0=禁用
MEMORY_ARCHIVE_MIN_INTERVAL_SECONDS=86400  # 跨进程节流间隔（默认 1 天）
```

**特性**：
- ✅ **跨进程节流**：避免多个 CLI 实例同时归档
- ✅ **Fail-soft**：归档失败不中断启动流程
- ✅ **保留核心约定**：文件头部的前 20 条永久保留
- ✅ **按月归档**：归档文件按月命名（如 `2026-09.md`）
- ✅ **可追溯**：归档文件保留完整历史记录

**集成点**：`src/heagent/cli/console.py::_prune_runtime_artifacts()`

### 3. 手动整理工具（按需使用）

**工具脚本**：`.heagent/tmp/clean_memory.py`

**使用场景**：
- 需要立即清理冗余条目
- 在自动归档之前手动整理
- 删除已固化在代码/文档中的过程性记录

**使用方法**：
```bash
python .heagent/tmp/clean_memory.py
```

## 实施效果

### 当前状态（手动整理后）
- ✅ 96 条事实，43486 字节
- ✅ 在预算内（49152 字节），余量 5666 字节
- ✅ 删除了 35 条已固化的过程性记录
- ✅ 不再触发超出预算警告

### 长期保障（自动归档启用后）
- ✅ 预算扩大到 96 KB，容纳更多条目
- ✅ 自动归档保持文件在可控大小
- ✅ 核心约定永久保留，历史可追溯
- ✅ 无需人工干预，系统自动维护

## 测试覆盖

**新增测试**：`tests/memory/test_auto_archive.py`（8 例测试）
- ✅ 配置禁用时不执行归档
- ✅ 文件不存在时跳过
- ✅ 无旧条目时跳过
- ✅ 归档旧事实并保留核心和近期
- ✅ 跨进程节流机制
- ✅ 按月创建归档文件
- ✅ 错误时 fail-soft
- ✅ 保留文件头部内容

**测试结果**：全部通过

## 配置建议

### 默认配置（推荐）
```bash
MEMORY_INJECT_MAX_BYTES=98304          # 96 KB 预算
MEMORY_AUTO_ARCHIVE_DAYS=90            # 90 天自动归档
MEMORY_ARCHIVE_MIN_INTERVAL_SECONDS=86400  # 1 天节流
```

### 保守配置（更频繁归档）
```bash
MEMORY_INJECT_MAX_BYTES=98304
MEMORY_AUTO_ARCHIVE_DAYS=60            # 60 天归档
MEMORY_ARCHIVE_MIN_INTERVAL_SECONDS=43200  # 12 小时节流
```

### 宽松配置（更大预算）
```bash
MEMORY_INJECT_MAX_BYTES=196608         # 192 KB 预算
MEMORY_AUTO_ARCHIVE_DAYS=180           # 180 天归档
MEMORY_ARCHIVE_MIN_INTERVAL_SECONDS=86400
```

### 禁用自动归档（仅手动整理）
```bash
MEMORY_INJECT_MAX_BYTES=98304
MEMORY_AUTO_ARCHIVE_DAYS=0             # 禁用自动归档
```

## 文件结构

```
.heagent/
├── memory/
│   ├── MEMORY.md              # 主记忆文件（自动维护）
│   ├── .archive-stamp         # 归档时间戳（跨进程节流）
│   └── archive/               # 归档目录
│       ├── 2026-09.md         # 2026年9月归档
│       ├── 2026-10.md         # 2026年10月归档
│       └── ...
└── tmp/
    └── clean_memory.py        # 手动整理工具
```

## 维护指南

### 查看当前状态
```bash
python -c "
from pathlib import Path
content = Path('.heagent/memory/MEMORY.md').read_text(encoding='utf-8')
facts = [l for l in content.split('\n') if l.strip().startswith('- ')]
fact_bytes = sum(len(f.encode('utf-8')) + 1 for f in facts)
print(f'Facts: {len(facts)}')
print(f'Bytes: {fact_bytes}')
print(f'Budget: 98304')
print(f'Usage: {fact_bytes / 98304 * 100:.1f}%')
"
```

### 手动触发归档
```bash
# 临时禁用节流
python -c "
from heagent.memory.auto_archive import maybe_archive_old_facts
from heagent.config import Settings
settings = Settings(
    memory_auto_archive_days=90,
    memory_archive_min_interval_seconds=0  # 禁用节流
)
result = maybe_archive_old_facts(settings=settings)
print(result)
"
```

### 查看归档历史
```bash
ls -lh .heagent/memory/archive/
```

## 迁移说明

### 现有项目
1. 更新配置文件（可选，使用默认值即可）
2. 下次 CLI 启动时自动生效
3. 首次归档会自动执行（如果有旧条目）

### 新项目
- 无需任何操作，开箱即用
- 自动归档机制默认启用

## 注意事项

1. **核心约定放在文件头部**：前 20 条事实永久保留，重要约定应放在文件顶部
2. **归档不是删除**：旧条目移动到 `archive/` 目录，可随时查阅
3. **Fail-soft 设计**：归档失败不影响系统运行
4. **跨进程安全**：多个 CLI 实例不会冲突
5. **预算仍可调整**：根据实际使用情况调整 `MEMORY_INJECT_MAX_BYTES`

## 相关文件

- `src/heagent/config/__init__.py` - 配置参数定义
- `src/heagent/memory/auto_archive.py` - 自动归档实现
- `src/heagent/cli/console.py` - CLI 启动集成
- `tests/memory/test_auto_archive.py` - 测试用例
- `.heagent/tmp/clean_memory.py` - 手动整理工具
