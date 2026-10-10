"""技能存储管理器（memory/skills 拆分层，Phase 4 C4）。

:class:`SkillStore` 是技能 CRUD 与使用追踪的门面：文件读取走
:func:`~heagent.tools.path_safety.open_text_under_root` 单一安全入口（围栏 +
O_NOFOLLOW + fstat），渲染/就地改写委托 :mod:`.skill_rewrite`，解析委托
:mod:`.skill_models`，meta.yaml 契约委托 :mod:`.skill_meta`，匹配/过期盘点委托
:mod:`.skill_catalog`。

存储路径：.heagent/skills/{name}/SKILL.md（触发面四键 + 正文）与
.heagent/skills/{name}/meta.yaml（包元数据 + 运行时计数）。record_usage 只回写
meta.yaml，SKILL.md 运行时只读。
"""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.pub.persist import atomic_update_text, atomic_write_text
from heagent.skills.skill_catalog import match_skill_details as _match_skill_details
from heagent.skills.skill_catalog import stale_skills as _stale_skills
from heagent.skills.skill_meta import META_FILENAME, SkillMeta, parse_meta_yaml, render_meta_yaml
from heagent.skills.skill_models import SkillContent, SkillRewriteError, parse_skill_md, validate_skill_name
from heagent.skills.skill_rewrite import (
    body_survives_rerender,
    key_line,
    metadata_lines,
    patch_frontmatter,
    render_skill_md,
)
from heagent.tools.path_safety import open_text_under_root

if TYPE_CHECKING:
    from heagent.skills.skill_models import SkillMatch

logger = logging.getLogger(__name__)


class SkillStore:
    """技能存储管理器，支持 CRUD 操作。

    每个技能以目录形式存储，SKILL.md 为入口文件，meta.yaml 为元数据/计数文件。
    """

    def __init__(self, base_dir: str = ".heagent/skills") -> None:
        self._base = Path(base_dir)
        # 本锁使同一实例的「读」与「写」互斥。并行子代理经 ``asyncio.to_thread``
        # 在多个工作线程里同时构建系统提示词（读技能文件做技能匹配）并调用
        # ``record_usage``（原子替换 meta.yaml），而 Windows 的 ``open`` 不共享删除
        # 权限：读者只要持有句柄，写者的 ``os.replace`` 就会以 ``WinError 5`` 失败。
        # 故读路径与写路径共用这一把锁；``atomic_write_text(lock=True)`` 的
        # ``.lock`` 文件锁另行覆盖跨进程场景，:func:`_replace_with_retry` 兜住瞬时占用。
        # 用 ``RLock`` 是因为 ``parse`` → ``load`` 等路径会嵌套获取。
        self._mutation_lock = threading.RLock()

    # 拆分兼容面：测试经类名访问这两个改写内核（原 SkillStore 静态方法，随 Phase 4 C4
    # 归位 skill_rewrite；别名保持类属性访问缝原位）。
    _render_skill_md = staticmethod(render_skill_md)
    _body_survives_rerender = staticmethod(body_survives_rerender)

    # ---- 路径工具 ----

    def _skill_dir(self, name: str) -> Path:
        """技能目录路径（名称规范化复用 validate_skill_name，保证 save/delete/load 路径一致）。"""
        return self._base / validate_skill_name(name)

    def _skill_md(self, name: str) -> Path:
        """SKILL.md 文件路径。"""
        return self._skill_dir(name) / "SKILL.md"

    def _meta_path(self, name: str) -> Path:
        """meta.yaml 文件路径。"""
        return self._skill_dir(name) / META_FILENAME

    def read_resource(self, name: str, resource: str) -> str | None:
        """Read one package-local resource through the SkillPackage integrity gate."""
        from heagent.skills.skill_packages import SkillPackage

        try:
            package = SkillPackage(skill_id=validate_skill_name(name), root=self._skill_dir(name))
            return package.read_resource(resource)
        except (ValueError, FileNotFoundError):
            return None

    def _read_text(self, path: Path) -> str:
        """读取技能文件，并与同实例的写操作互斥。

        Phase 4 C4：经 :func:`open_text_under_root` 单一安全入口（围栏 + 最终组件
        O_NOFOLLOW + fstat 普通文件校验）。见 :meth:`__init__` 的锁说明：Windows 上
        读者持句柄会让写者的 ``os.replace`` 失败，故读路径不得与写路径并发。文件缺失
        抛 ``FileNotFoundError``，由调用方（如 :meth:`load`）决定语义。
        """
        with self._mutation_lock:
            return open_text_under_root(self._base, path)

    def _read_meta(self, name: str) -> SkillMeta:
        """读取 meta.yaml；缺文件返回全默认（纯声明面技能的常态）。"""
        try:
            return parse_meta_yaml(self._read_text(self._meta_path(name)))
        except FileNotFoundError:
            return SkillMeta()

    # ---- CRUD ----

    def save(
        self,
        name: str,
        description: str,
        pattern: str,
        steps: list[str],
        *,
        tags: list[str] | None = None,
        triggers: list[str] | None = None,
        negative_triggers: list[str] | None = None,
        priority: int = 0,
        usage_count: int = 0,
        last_used: str = "",
        created: str | None = None,
    ) -> str:
        """保存一个技能为标准目录结构。

        创建 skills/<name>/SKILL.md（触发面四键 + 正文）与 skills/<name>/meta.yaml
        （tags/priority/usage_count/last_used/created），返回 SKILL.md 的路径。

        ``created`` 为 None 时自动生成当前时间；``update()`` / ``record_usage()``
        透传原值，防止每次调用覆写原始创建时间（P1-7 修复）。
        """
        safe = validate_skill_name(name)
        skill_dir = self._base / safe

        if created is None:
            created = datetime.now().isoformat()
        content = self._render_skill_md(
            safe,
            description,
            pattern,
            steps,
            triggers=triggers,
            negative_triggers=negative_triggers,
        )
        meta = SkillMeta(
            tags=tags or [],
            priority=priority,
            usage_count=usage_count,
            last_used=last_used,
            created=created,
        )
        md_path = skill_dir / "SKILL.md"
        with self._mutation_lock:
            skill_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(md_path, content, lock=True)
            atomic_write_text(skill_dir / META_FILENAME, render_meta_yaml(meta), lock=True)
        return str(md_path)

    def load(self, name: str) -> str | None:
        """按名称加载 SKILL.md 内容。不存在或名称非法返回 None。"""
        try:
            path = self._skill_md(name)
        except ValueError:
            return None
        try:
            return self._read_text(path)
        except FileNotFoundError:
            return None

    def list_skills(self) -> list[str]:
        """返回所有已存储的技能名称（目录名，按名称排序）。"""
        if not self._base.exists():
            return []
        return sorted(d.name for d in self._base.iterdir() if d.is_dir() and (d / "SKILL.md").exists())

    def delete(self, name: str) -> bool:
        """删除指定技能目录。返回是否成功删除。"""
        try:
            skill_dir = self._skill_dir(name)
        except ValueError:
            return False
        with self._mutation_lock:
            if skill_dir.is_dir():
                shutil.rmtree(skill_dir)
                return True
        return False

    def all_skills_content(self) -> list[str]:
        """返回所有技能 SKILL.md 的完整内容（用于注入系统提示词）。"""
        if not self._base.exists():
            return []
        contents: list[str] = []
        for name in self.list_skills():
            raw = self.load(name)
            if raw:
                contents.append(raw)
        return contents

    # ---- 解析与更新 ----

    def parse(self, name: str) -> SkillContent | None:
        """将 SKILL.md ⊕ meta.yaml 解析为结构化字段。不存在返回 None。

        触发面字段来自 SKILL.md，元数据/计数字段来自 meta.yaml（缺文件取默认）。
        """
        raw = self.load(name)
        if raw is None:
            return None
        content = parse_skill_md(name, raw)
        meta = self._read_meta(name)
        return content.model_copy(
            update={
                "created": meta.created,
                "tags": meta.tags,
                "priority": meta.priority,
                "usage_count": meta.usage_count,
                "last_used": meta.last_used,
            }
        )

    def update(
        self,
        name: str,
        *,
        description: str | None = None,
        pattern: str | None = None,
        steps: list[str] | None = None,
        tags: list[str] | None = None,
        triggers: list[str] | None = None,
        negative_triggers: list[str] | None = None,
        priority: int | None = None,
    ) -> str | None:
        """部分更新已有技能，并把读、合并、写入置于同一跨进程事务中。

        SKILL.md 事务（description/pattern/steps/triggers/negative_triggers）与
        meta.yaml 事务（tags/priority）各自持锁原子替换；两文件间没有跨文件不变量，
        无需跨文件事务。``atomic_update_text`` 持有各自的文件锁，因此与 ``record_usage``
        或另一个 ``SkillStore`` 实例的更新不会以旧快照覆盖彼此的变更。
        """
        try:
            md_path = self._skill_md(name)
        except ValueError:
            return None

        def apply(raw: str) -> tuple[str, bool]:
            if not raw:
                return raw, False
            existing = parse_skill_md(name, raw)
            if not self._body_survives_rerender(raw):
                if pattern is not None or steps is not None:
                    raise SkillRewriteError(
                        f"skill '{name}' has body sections outside '## Pattern'/'## Steps'; rewriting "
                        "pattern/steps would drop them. Reflow the body into those two sections first, "
                        "or update only description/triggers/negative_triggers."
                    )
                merged = metadata_lines(
                    name=name,
                    description=description if description is not None else existing.description,
                    triggers=existing.triggers if triggers is None else triggers,
                    negative_triggers=existing.negative_triggers if negative_triggers is None else negative_triggers,
                )
                upserts: dict[str, str] = {}
                removals: list[str] = []
                for key, value in (
                    ("description", description),
                    ("triggers", triggers),
                    ("negative_triggers", negative_triggers),
                ):
                    if value is None:
                        continue
                    rendered = key_line(merged, key)
                    if rendered is None:
                        removals.append(key)
                    else:
                        upserts[key] = rendered
                if not upserts and not removals:
                    return raw, True
                patched = patch_frontmatter(raw, upserts, removals)
                if patched is None:
                    raise SkillRewriteError(
                        f"skill '{name}' has no frontmatter block; updating metadata in place would require rewriting the body."
                    )
                return patched, True
            return (
                self._render_skill_md(
                    name,
                    description if description is not None else existing.description,
                    pattern if pattern is not None else existing.pattern,
                    steps if steps is not None else existing.steps,
                    triggers=triggers if triggers is not None else existing.triggers,
                    negative_triggers=negative_triggers
                    if negative_triggers is not None
                    else existing.negative_triggers,
                ),
                True,
            )

        with self._mutation_lock:
            updated = atomic_update_text(md_path, apply)
            if tags is not None or priority is not None:

                def apply_meta(meta_raw: str) -> tuple[str, bool]:
                    meta = parse_meta_yaml(meta_raw) if meta_raw.strip() else SkillMeta()
                    meta_updates: dict[str, object] = {}
                    if tags is not None:
                        meta_updates["tags"] = tags
                    if priority is not None:
                        meta_updates["priority"] = priority
                    return render_meta_yaml(meta.model_copy(update=meta_updates)), True

                atomic_update_text(self._meta_path(name), apply_meta)
        return str(md_path) if updated else None

    # ---- 使用追踪与策展 ----

    def record_usage(self, name: str) -> None:
        """递增技能使用计数并更新最后使用时间（只写 meta.yaml，SKILL.md 零写入）。"""
        if self.load(name) is None:
            return

        def increment(meta_raw: str) -> tuple[str, bool]:
            meta = parse_meta_yaml(meta_raw) if meta_raw.strip() else SkillMeta()
            updated = meta.model_copy(
                update={"usage_count": meta.usage_count + 1, "last_used": datetime.now().isoformat()}
            )
            return render_meta_yaml(updated), True

        with self._mutation_lock:
            atomic_update_text(self._meta_path(name), increment)

    def stale_skills(self, days: int = 30) -> list[str]:
        """返回超过 N 天未使用的技能名称列表。"""
        return _stale_skills(self, days)

    def archive(self, name: str) -> bool:
        """将技能目录移动到 .heagent/skills/.archive/。"""
        try:
            src = self._skill_dir(name)
        except ValueError:
            return False
        archive_dir = self._base / ".archive"
        with self._mutation_lock:
            if not src.is_dir():
                return False
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(archive_dir / name))
            return True

    # ---- 匹配 ----

    def match_skill_details(self, prompt: str, threshold: float) -> list[SkillMatch]:
        """Return explainable, backward-compatible skill matches."""
        return _match_skill_details(self, prompt, threshold)
