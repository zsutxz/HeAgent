"""用户级 ``setting.md``：读 / 写 / 渲染 / 一次性迁移 + pydantic-settings 用户层源。

双层配置的**用户层**从 ``~/.heagent/.env`` 换成 ``~/.heagent/setting.md``（YAML frontmatter +
正文人类注释）：``.env`` 从此是项目级专用格式，用户级用可读可注释的 markdown。生效优先级
（由 ``Settings.settings_customise_sources`` 的源元组顺序决定，见 ``config/__init__.py``）：

    系统环境变量 > 项目 ``.env`` > 用户 ``setting.md`` > 字段默认值

三条硬边界：

- **用户层永久只读**（脊柱 I4）：本模块只有一次性迁移会写 ``setting.md``；写通道
  （:mod:`heagent.config.write`）的目的地仍然只能是项目 ``.env``。
- **迁移一次、终态唯一**：:func:`ensure_user_settings_migrated` 把旧 ``~/.heagent/.env`` 搬进
  ``setting.md`` 后把旧文件改名 ``.env.migrated``；此后任何代码路径都不再读旧文件（它不在
  任何源里）。
- **显性失败**：``setting.md`` 无 frontmatter / 语法错 / 重复键抛 :class:`SettingsError`，
  绝不半解析兜底——配置系统坏了就该让用户立刻看见。

依赖面：stdlib + ``heagent.pub`` + 同包 ``envfile`` + ``pydantic_settings``；**不得** import
``heagent.config``（``__init__``），路径一律走参数——``Settings`` 接线本模块时不得成环。
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_settings import PydanticBaseSettingsSource

from heagent.config.envfile import check_key, parse_index, parse_value, read_value
from heagent.pub.frontmatter import FrontmatterSyntaxError, parse_strict_pairs, split_frontmatter
from heagent.pub.persist import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

#: 用户级配置文件名（相对 ``~/.heagent/``）。
SETTING_FILENAME = "setting.md"

#: 旧 ``.env`` 迁移后的改名后缀（``~/.heagent/.env`` → ``~/.heagent/.env.migrated``）。
MIGRATED_SUFFIX = ".migrated"


class SettingsError(ValueError):
    """用户级 ``setting.md`` 无法加载（无 frontmatter / 语法错）或迁移写盘失败；显性失败不兜底。"""


def read_setting_md(path: Path) -> dict[str, str]:
    """读取用户级 ``setting.md`` 的 frontmatter 键值（键小写化）。

    文件缺失或为空 → ``{}``（与 ``.env`` 层「不存在即未提供」同语义）；有内容但无 frontmatter、
    或 frontmatter 语法错（含重复键）→ :class:`SettingsError`（链 ``FrontmatterSyntaxError``）。
    文件头 UTF-8 BOM 由 ``split_frontmatter`` 容忍。值清理复用 :func:`envfile.parse_value`
    （strip → 剥行内注释 → 剥成对引号）——与 dotenv 源**同一口径**，两层值语义不漂移；刻意
    **不做**标量 coercion（``parse_scalar`` 会把 ``true`` 变布尔、再被 pydantic 串化成
    ``"True"``，静默篡改配置值）。
    """
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    split = split_frontmatter(text)
    if split is None:
        raise SettingsError(
            f"{path}: setting.md 有内容但缺少 YAML frontmatter 头（首行须为 ``---``，键值对写在两个 ``---`` 之间）"
        )
    try:
        pairs = parse_strict_pairs(split[0])
    except FrontmatterSyntaxError as exc:
        raise SettingsError(f"{path}: 第 {exc.line_number} 行无法解析（{exc.kind}）：{exc.line!r}") from exc
    return {key.lower(): parse_value(value) for key, value in pairs.items()}


def render_setting_md(pairs: Mapping[str, str], *, body: str = "") -> str:
    """渲染 ``setting.md`` 文本：``KEY: value`` frontmatter + 正文。

    值默认裸写；**往返校验不过**（读侧 ``parse_value`` 会改变它——行内注释、成对引号等）时
    外包一层双引号再验，仍不可表达才抛 :class:`SettingsError`。值含控制字符或首尾空白
    （后者几乎必然是笔误）直接拒绝——写不出保真内容就大声失败。空键值对时 frontmatter 内
    写一行注释占位，保证文件结构仍可解析。
    """
    lines: list[str] = []
    for key, value in pairs.items():
        check_key(key)
        if "\r" in value or "\n" in value or "\x00" in value:
            raise SettingsError(f"{key}: value contains a control character and cannot live in setting.md")
        if value != value.strip():
            raise SettingsError(f"{key}: value has leading or trailing whitespace and cannot round-trip setting.md")
        text_value = value
        if parse_value(value) != value:
            text_value = f'"{value}"'
            if parse_value(text_value) != value:
                raise SettingsError(f"{key}: value {value!r} cannot round-trip through setting.md")
        lines.append(f"{key}: {text_value}")
    if not lines:
        lines = ["# （空配置——保留本行使 frontmatter 结构完整）"]
    text = "---\n" + "\n".join(lines) + "\n---\n"
    body = body.strip()
    return f"{text}\n{body}\n" if body else text


def write_setting_md(path: Path, text: str) -> None:
    """原子写 ``setting.md``（``persist.atomic_write_bytes``：同目录临时文件 + replace，
    中断不会留下截断文件）。"""
    atomic_write_bytes(path, text.encode("utf-8"))


def parse_legacy_env_pairs(path: Path) -> dict[str, str]:
    """旧 ``.env`` → 有序键值（envfile 口径：同键后者胜、剥行内注释、剥引号）；缺失 → ``{}``。

    用 ``utf-8-sig`` 读入把 BOM 透明剥离——``parse_index`` 自身容忍 BOM，但 ``read_value``
    的行级扫描不剥，首行键会被读成 ``\\ufeffKEY`` 而漏迁。
    """
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    index = parse_index(text)
    return {key: read_value(text, key) or "" for key in index.keys}


def _rename_legacy(legacy: Path, migrated: Path) -> None:
    """旧 ``.env`` 改名归档；失败不阻塞（md 已落盘即迁移实质完成，残留旧文件不在任何源里）。"""
    try:
        os.rename(legacy, migrated)
    except FileExistsError:
        pass  # 并发迁移方已改名（Windows rename 目标存在即抛）；终态一致
    except OSError as exc:
        logger.warning("旧配置 %s 改名为 %s 失败（不阻塞配置加载）：%s", legacy, migrated, exc)


def ensure_user_settings_migrated(setting_file: Path, *, legacy_env_file: Path | None) -> bool:
    """把旧 ``~/.heagent/.env`` 一次性迁移进 ``setting.md``（幂等）；返回是否执行了迁移。

    ``legacy_env_file=None`` **显式禁用**迁移（注入层 / 密封态一律传 None——绝不从目录布局
    猜测 legacy 位置，否则面板沙箱里 setting.md 的同目录 ``.env``（项目配置）会被误改名）。

    锚定后的四态：md 在 + legacy 在 → legacy 顺手改名归档（终态唯一），返回 ``False``；
    md 在 → 幂等出口；都不在 → 跳过；md 不在 + legacy 在 → 迁移（先原子写 md、后改名 legacy
    ——崩溃窗口只可能留下「双份」，绝不丢配置；双份态下次进入第一支收尾）。
    """
    if legacy_env_file is None:
        return False
    legacy = legacy_env_file
    migrated = Path(f"{legacy}{MIGRATED_SUFFIX}")
    if setting_file.exists():
        if legacy.exists():
            _rename_legacy(legacy, migrated)
        return False
    if not legacy.exists():
        return False
    pairs = parse_legacy_env_pairs(legacy)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = f"由 `{legacy.name}` 自动迁移于 {stamp}；原文件已改名 `{migrated.name}`。"
    try:
        write_setting_md(setting_file, render_setting_md(pairs, body=body))
    except SettingsError:
        raise
    except OSError as exc:
        raise SettingsError(f"{setting_file}: 迁移写盘失败：{exc}") from exc
    _rename_legacy(legacy, migrated)
    return True


class UserMarkdownSettingsSource(PydanticBaseSettingsSource):
    """用户层 ``setting.md`` 源：**取值时**先确保迁移，再严格解析。

    迁移钩子放在 ``__call__``（取值路径）而不是构造路径：源被实例化不代表被取值——放在这里
    才能覆盖「任何真正读配置的地方」（``get_settings``、直接构造、面板求解、写通道候选）。
    返回键小写化（与 env / dotenv 源同口径）；``setting_file=None`` 表示禁用本层。
    """

    def __init__(self, settings_cls: type[Any], *, setting_file: Path | None) -> None:
        super().__init__(settings_cls)
        self._setting_file = setting_file
        self._legacy_env_file = getattr(settings_cls, "_legacy_env_file", None)

    def get_field_value(self, field: Any, field_key: str) -> tuple[Any, Any, bool]:
        """逐字段接口（基类抽象方法）；批量源在 ``__call__`` 一次取全部——误用即大声失败。"""
        raise NotImplementedError("UserMarkdownSettingsSource is a batch source; only __call__ is supported")

    def __call__(self) -> dict[str, Any]:
        if self._setting_file is None:
            return {}
        ensure_user_settings_migrated(self._setting_file, legacy_env_file=self._legacy_env_file)
        return dict(read_setting_md(self._setting_file))


#: 动态子类缓存：面板每次请求都会构造一次 Settings，模型类不能反复重建。
_LAYER_CACHE: dict[tuple[str, int], type[Any]] = {}


def with_user_setting_layer(setting_file: Path | None, base: type[Any]) -> type[Any]:
    """派生 ``_user_setting_file`` 被改写的 ``base`` 子类（memoize）。

    供 catalog / write 通道**逐调用**注入受控路径（测试密封）或 ``None``（禁用 md 层）。
    注入层的 ``_legacy_env_file`` 一律 ``None``——注入路径永不触发迁移/归档（否则面板沙箱里
    md 的同目录 ``.env`` 会被误当作 legacy 改名，见 conftest 密封与 catalog 沙箱用例）。
    不用 pydantic-settings 2.14 新增的 ``_build_sources``：那要求抬高依赖下限声明，且是带
    下划线的非稳定接口。
    """
    key = (str(setting_file), id(base))
    layer = _LAYER_CACHE.get(key)
    if layer is None:
        layer = type(
            f"{base.__name__}UserSettingLayer",
            (base,),
            {"_user_setting_file": setting_file, "_legacy_env_file": None},
        )
        _LAYER_CACHE[key] = layer
    return layer


__all__ = [
    "MIGRATED_SUFFIX",
    "SETTING_FILENAME",
    "SettingsError",
    "UserMarkdownSettingsSource",
    "ensure_user_settings_migrated",
    "parse_legacy_env_pairs",
    "read_setting_md",
    "render_setting_md",
    "with_user_setting_layer",
    "write_setting_md",
]
