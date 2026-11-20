# 示例：技能包开发

演示一个**能直接被 `SkillStore` 解析**的技能包：`release-notes/`。

```text
release-notes/
├── SKILL.md              # 入口：frontmatter（name / description / triggers）+ 正文（Pattern / Steps / 资源）
└── scripts/
    └── group_commits.py  # 可选辅助资源（技能正文里引用它）
```

## 校验它真的能被加载

```bash
python -c "
from heagent.skills.skill_store import SkillStore
s = SkillStore('examples/skill-package')
print(s.list_skills())
c = s.parse('release-notes')
print(c.name, bool(c.description), len(c.steps), c.pattern[:20])
"
```

期望输出：

```text
['release-notes']
release-notes True 24 发布说明|发布公告|release no
```

三个数各自的意思：`list_skills()` 有该项 = 技能能被目录收录；`bool(c.description)` 为 `True` =
frontmatter 的 `description` 非空（`canonical_id` 由 `SkillPackage` 侧按 `name` 规范化，本示例同为
`release-notes`）；`len(c.steps)` 是解析出的步骤行数（正文 `## Steps` 段里的非空行，随正文调整会变，
只校验非 0）；`pattern[:20]` 截到 20 个字符。

## 装进技能库

技能库是**双根且全局优先**：

| 根 | 位置 | 生效顺序 |
| --- | --- | --- |
| 全局 | `~/.heagent/skills/<name>/` | 先（同名时这版生效） |
| 项目 | `<repo>/.heagent/skills/<name>/` | 后（同名被遮蔽并告警） |

前提：仓库已 `pip install -e .`（否则 `import heagent` 失败）。

```bash
# 项目级安装（推荐：只在本仓库生效）
mkdir -p .heagent/skills
cp -r examples/skill-package/release-notes .heagent/skills/
```

装完在交互模式里用 `skill_list` 或直接触发（说「帮我写发布说明」）验证。

## SKILL.md 的硬约束

1. **必须有 frontmatter**：`name` 与 `description` 非空。缺 `SKILL.md` 的目录不会被 `list_skills()`
   收录；缺 frontmatter 的 `name` 会回落到目录名。
2. **`description` 决定自动触发**：模型按它判断「什么时候该用这个技能」，所以写「做什么 + 什么时候用」，
   不要只写一句口号。
3. **`## Pattern` 与 `## Steps` 是结构化字段**：`SkillStore.parse()` 会把它们读成 `pattern` / `steps`。
   不写不报错，但技能正文的步骤就只剩自由文本，匹配与注入都变弱。
4. **资源用相对路径引用**：正文里写 `scripts/group_commits.py`，读取走 `SkillStore.read_resource(name, path)`
   ——它会做路径围栏校验，不要自己拼绝对路径。
5. **不要提交 `meta.yaml`**：那是 `record_usage` 的计数文件（`usage_count` / `last_used`），由运行时写。
   本示例目录里刻意没有它。

## 相关

- 技能匹配阈值与自动注入预算：`SKILL_MATCH_THRESHOLD` / `SKILL_MAX_AUTO_INVOKE` /
  `SKILL_MAX_AUTO_INVOKE_TOKENS`（三个键的默认值与注释在 `.env.example` 的「技能 / 记忆 / 上下文」节）。
- `/goal` 声明式工作流的技能包契约更严（还要 `workflow.md` 等），见 [`docs/framework.md` §4.13](../../docs/framework.md#413-goal-驱动工作流-goal)。
