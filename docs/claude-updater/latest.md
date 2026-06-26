# Claude Code 生态更新报告

*生成时间：2026-06-26 16:53*

本次范围：**bmad-method 框架**（用户指令「bmad 也需要更新」）。CLI 与其余插件本次未动（上一会话已更新，见 `history/2026-06-26_165345.md`）。

> bmad-method **不属于** `claude plugin` 体系——它是独立框架（`bmad-code-org/BMAD-METHOD`），经 `npx bmad-method install` 装入项目 `_bmad/`。本次通过重跑 installer 升级。

## bmad-method

| 模块 | 更新前 | 更新后 | 状态 |
|------|--------|--------|------|
| core | 6.8.0 | 6.9.0 | ✅ |
| bmm（BMad Method） | 6.8.0 | 6.9.0 | ✅ |
| bmb（BMad Builder） | main | main @ e6935f2 | ✅ refreshed |
| gds（BMad Game Dev Studio） | main | main @ 46c3a6c | ✅ refreshed |

整体版本：**6.8.0 → 6.9.0**；Last Updated 2026/6/26。

## 执行步骤

1. `npx bmad-method status` → 确认当前 6.8.0，`npx` 拉到的最新发布版 6.9.0
2. `npx bmad-method install --action quick-update --yes --directory E:/AI/HeAgent` → 成功，4 模块更新

> ⚠️ **`--action update --yes` 不可用**：仍会进入交互向导并卡在 `Installation directory:` prompt（`--yes` 未跳过该确认）。改用 `quick-update`（专为非交互快速同步设计）+ 显式 `--directory` 解决。后续更新沿用此命令。

## 变更范围

更新重写了 installer-managed 文件与项目级 skills，**共 109 个文件**变动（66 改 / 27 删 / 16 新增）：

- `_bmad/`：`config.toml`、各模块 `config.yaml`、`scripts/`、`_config/*manifest*` 等 installer-managed 文件更新；新增 `_bmad/bmb/`、`_bmad/gds/` 模块目录、`_bmad/scripts/memlog.py`
- `.claude/skills/bmad-*`：6.9.0 skill 体系重构（大量 `steps/` 重排、`SKILL.md` 更新）
- `.agents/skills`（codex）：整目录新增（84 skills）
- `Custom files preserved: 2`——`_bmad/custom/` 与 `config.user.toml` 未被触碰

## 清理

- `_bmad/config.toml.bak`（installer 覆盖 `config.toml` 前的备份）已删除：diff 确认新版已正确重生成、用户持久配置在 `custom/` 已保留，旧备份无价值。

## ⚠️ 后续

- 上述 109 文件的 diff **尚未 commit**——请 review 后提交（`git status` / `git diff` 查看）。
- skills 变更需**重启 Claude Code** 后才生效。
- bmad 工作流渐增地依赖 `uv run` 跑 Python 脚本——installer 报告 uv 0.10.8 已检测到，可用。
