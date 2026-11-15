"""把 `.claude/skills/bmad-*` 的角色方法同步成 HeAgent 技能包（落 `.heagent/skills/`）。

为什么需要：HeAgent 的技能根只有 `~/.heagent/skills` 与 `<repo>/.heagent/skills`，`.claude/skills/`
对它不可见；而 BMAD v7 的角色只装在 `.claude/skills/`，其中 workflow 类角色（`bmad-build` /
`bmad-build-auto` / `bmad-agent-po` / `bmad-qa-generate-e2e-tests` / `bmad-code-review` /
`bmad-retrospective`）的 `SKILL.md` 只是「跑 `uv run render_skill.py`」的启动器——本机没有 `uv`，
子会话无法直接用它。不同步就会在 `/loop` 起跑时解析不到「执行角色」。

做法（幂等，可反复跑）：
1. 复制源包（`assets/` `references/` `scripts/` `config/` `step-*.md` `workflow.md` 等），跳过 `evals/`；
2. 有 `workflow.md` 的角色用仓库内 `_bmad/scripts/render_skill.py` 预渲染，把结果里的
   `_bmad/render/<role>/<proj>/<snap>/` 绝对路径改写为包内相对路径（被引用的快照文件缺则补拷）；
3. 重写 `SKILL.md`：保留 `name` / `description`，补 `triggers` / `negative_triggers`（触发面四键），
   正文 =「HeAgent 执行适配」+ 预渲染执行契约或原角色契约（`uv run` → `python`）；
4. 写 `meta.yaml`（`canonical_id: bmad-<role>`），供技能目录按 id/别名解析。

用法::

    python scripts/sync_bmad_role_skills.py            # 同步 + 自检
    python scripts/sync_bmad_role_skills.py --check    # 只自检，不写盘

前置：渲染需要 `jinja2`（构建期工具，不在依赖树里——`python -m pip install jinja2`，同 `mkdocs` 口径）；
缺它且存在 workflow 类角色时显性失败，不静默跳过渲染（跳过会得到「启动器当契约」的坏包）。

退出码：``0`` = 同步完成且自检通过；``1`` = 前置缺失 / 渲染失败 / 自检不合格。
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / ".claude" / "skills"
DST_ROOT = ROOT / ".heagent" / "skills"
RENDERER = ROOT / "_bmad" / "scripts" / "render_skill.py"

#: 同步范围 = 两份工作流（`/loop` 的 v7 契约与 `/goal` 的 v6 契约）声明的全部执行角色 + 文档引擎。
ROLES: tuple[str, ...] = (
    "bmad-agent-analyst",
    "bmad-agent-pm",
    "bmad-agent-po",
    "bmad-agent-architect",
    "bmad-architecture",
    "bmad-brainstorming",
    "bmad-build",
    "bmad-build-auto",
    "bmad-code-review",
    "bmad-retrospective",
    "bmad-qa-generate-e2e-tests",
    "bmad-facilitate",
)

#: 未装进 HeAgent 技能库的辅助技能：方法正文里的「invoke X」对这些名字一律不执行。
AUX_SKILLS = ("bmad", "bmad-party-mode", "bmad-advanced-elicitation", "bmad-review", "bmad-ux", "bmad-deep-recon")

ADAPT_HEAD = """## HeAgent 执行适配（BMAD v7 同步）

本包是 `.claude/skills/{role}/` 的 HeAgent 侧副本：角色方法的真源仍是那份 v7 安装，本包只做
「让 HeAgent 的技能库能按角色名解析到它」的适配，不新增方法论。`.claude/skills` 更新后重跑
`python scripts/sync_bmad_role_skills.py` 即可。

- **没有 `uv`、没有 `npx`**：正文里的 `uv run <script>` 一律改为宿主可用解释器直接跑
  （`python <script>`；脚本要 `PyYAML` / `jinja2` 时先用项目 venv 装上）；`npx skills add …` 不执行，
  缺依赖就如实上报给宿主，不要静默降级。
- **恒为 headless**：没有人坐在对面——不问候、不提问、不以等待用户收尾；缺口写成 `gap` /
  `Open question:`，可默认的写 `Assumption:`。
- **路径约定**：`{{project-root}}` = 仓库根（含 `_bmad/` 的目录）；`{{skill-root}}` = 本包目录
  `.heagent/skills/{role}/`（相对仓库根，用 `file_read` 读，路径围栏只认相对/宿主形态）。
- **辅助技能缺装**：{aux} 未装进 HeAgent 技能库，方法里「invoke X」在这些名字上**一律不执行**：
  能等价内置的就地做（`bmad-review` 的 diff 评审用 `bmad-code-review`），否则写成 `gap` 上报给宿主。
- **规划真源 = v7 票树**：产物在 `_bmad-output/initiative-<slug>/`；story 状态只经
  `python _bmad/method/scripts/tickets.py --project-root <repo> mark <ref> <status>` 写，
  不写 `epics.md`、不写 `_bmad-output/sprint-status.yaml`。
"""

SNAPSHOT_REF = re.compile(
    r"_bmad/render/(?P<role>[A-Za-z0-9._-]+)/(?P<proj>[A-Za-z0-9._-]+)/(?P<snap>[A-Za-z0-9._-]+)/"
)
PACKAGE_REF = re.compile(r"\.heagent/skills/([A-Za-z0-9._-]+)/([A-Za-z0-9._/-]+)")


def fail(message: str) -> None:
    """显性失败：前置缺失或渲染失败时打印原因并退出 1（绝不静默降级成半成品包）。"""
    print(f"[sync] FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """拆 SKILL.md 的 frontmatter（只取单行 `key: value`，与 HeAgent 的宽档解析同口径）。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fields: dict[str, str] = {}
    for line in text[3:end].strip("\n").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields, text[end + 4 :].lstrip("\n")


def copy_package(role: str, dst: Path) -> None:
    src = SRC_ROOT / role
    if not src.is_dir():
        fail(f"源包缺失: {src}（先装 BMAD v7 角色，或把该角色从 ROLES 里去掉）")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("evals", "__pycache__", "*.pyc"))


def render_workflow(role: str, dst: Path) -> str | None:
    """预渲染 workflow 类角色；无 `workflow.md` 的角色返回 None（其 SKILL.md 本身就是契约）。"""
    if not (dst / "workflow.md").is_file():
        return None
    if not RENDERER.is_file():
        fail(f"渲染器缺失: {RENDERER}（BMAD 未安装或版本过旧）")
    if importlib.util.find_spec("jinja2") is None:
        fail("渲染需要 jinja2：python -m pip install jinja2（构建期工具，同 mkdocs 口径）")
    completed = subprocess.run(
        [sys.executable, str(RENDERER), "--project-root", str(ROOT), "--skill", str(dst)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    out = completed.stdout
    if completed.returncode != 0 or out.lstrip().startswith("HALT:"):
        detail = (out or completed.stderr).strip()[:400]
        fail(f"{role} 渲染失败（exit={completed.returncode}）: {detail}")
    return _rewrite_snapshot_paths(role, dst, out)


def _rewrite_snapshot_paths(role: str, dst: Path, out: str) -> str:
    """把渲染结果里的快照绝对路径改写为包内相对路径，并补齐被引用的快照文件。"""
    match = SNAPSHOT_REF.search(out)
    if match is None:
        return out
    snapshot_root = ROOT / "_bmad" / "render" / role / match.group("proj") / match.group("snap")
    if snapshot_root.is_dir():
        for line in out.splitlines():
            marker = f"{snapshot_root}/"
            if marker not in line:
                continue
            rel = line.split(marker, 1)[1].split("`")[0].strip()
            source = snapshot_root / rel
            target = dst / rel
            if source.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
    return out.replace(f"{snapshot_root}/", f".heagent/skills/{role}/")


def normalize_body(body: str) -> str:
    """`uv run` 归一：本机无 uv，正文里的脚本调用一律落回 `python`。"""
    return body.replace("uv run --no-cache ", "python ").replace("uv run ", "python ")


def write_skill(role: str, dst: Path, rendered: str | None) -> None:
    fields, body = split_frontmatter((dst / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
    name = fields.get("name", role).strip().strip("'\"")
    description = fields.get("description", "").strip()
    head = ADAPT_HEAD.format(role=role, aux=" / ".join(f"`{item}`" for item in AUX_SKILLS))
    if rendered is not None:
        contract = (
            "## 执行契约（预渲染自 v7 `workflow.md`）\n\n"
            f"下面是本角色的完整执行契约（官方 `render_skill.py` 输出，路径已改写为包内相对路径）。\n"
            f"需要逐步展开时用 `file_read` 读 `.heagent/skills/{role}/` 下同名文件"
            "（`step-*.md` / `references/` / `assets/`）。\n\n---\n\n" + rendered.strip() + "\n"
        )
    else:
        contract = "## 角色契约\n\n" + body.strip() + "\n"
    frontmatter = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"triggers: [{name}, /loop {name}, {name} 角色]\n"
        "negative_triggers: []\n"
        "---\n\n"
    )
    text = frontmatter + head + "\n" + normalize_body(contract)
    (dst / "SKILL.md").write_text(text, encoding="utf-8", newline="\n")


def write_meta(role: str, dst: Path) -> None:
    meta = (
        f"canonical_id: {role}\n"
        "tags: [bmad, role]\n"
        f"created: {date.today().isoformat()}\n"
        "priority: 3\n"
        "usage_count: 0\n"
        'last_used: ""\n'
    )
    (dst / "meta.yaml").write_text(meta, encoding="utf-8", newline="\n")


def check_package(role: str) -> list[str]:
    """自检：入口/元数据在位、适配块在位、包内引用全部落盘、无残留快照绝对路径。"""
    dst = DST_ROOT / role
    problems: list[str] = []
    skill = dst / "SKILL.md"
    if not skill.is_file():
        return [f"{role}: SKILL.md 缺失"]
    if not (dst / "meta.yaml").is_file():
        problems.append(f"{role}: meta.yaml 缺失")
    text = skill.read_text(encoding="utf-8", errors="replace")
    if "## HeAgent 执行适配" not in text:
        problems.append(f"{role}: 适配块缺失")
    if "_bmad/render/" in text or "uv run --no-cache" in text:
        problems.append(f"{role}: 残留快照绝对路径或未归一的 uv 调用")
    for owner, rel in PACKAGE_REF.findall(text):
        if not (DST_ROOT / owner / rel).exists():
            problems.append(f"{role}: 悬空引用 {owner}/{rel}")
    return problems


def sync(role: str) -> tuple[int, int]:
    """同步一个角色，返回 (文件数, 字节数)。"""
    dst = DST_ROOT / role
    copy_package(role, dst)
    rendered = render_workflow(role, dst)
    write_skill(role, dst, rendered)
    write_meta(role, dst)
    files = [path for path in dst.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 .claude/skills/bmad-* 同步成 HeAgent 技能包")
    parser.add_argument("--check", action="store_true", help="只自检现有包，不写盘")
    parser.add_argument("--roles", default="", help="逗号分隔的角色子集（默认全部）")
    args = parser.parse_args(argv)
    roles = tuple(item.strip() for item in args.roles.split(",") if item.strip()) or ROLES

    if not args.check:
        DST_ROOT.mkdir(parents=True, exist_ok=True)
        for role in roles:
            count, size = sync(role)
            print(f"[sync] {role:32s} files={count:3d} bytes={size:7d}")

    problems: list[str] = []
    for role in roles:
        found = check_package(role)
        problems.extend(found)
        if args.check:
            print(f"[check] {role:32s} {'ok' if not found else 'PROBLEM'}")
    if problems:
        for item in problems:
            print(f"[sync] problem: {item}", file=sys.stderr)
        return 1
    print(f"[sync] {len(roles)} 个角色包就绪（{DST_ROOT}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
