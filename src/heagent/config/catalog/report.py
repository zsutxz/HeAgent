"""报表装配：配置项、分组、未知键与路由池视图。

自 ``heagent.config.catalog`` 单文件拆出（E3 绞杀者），行为零改动。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from heagent.config import GLOBAL_SETTING_FILE, Settings

from .classify import classify
from .envscan import SettingMdScan, bom_prefixed_keys, scan_env_file, scan_setting_md
from .groups import EXCLUSION_GROUPS, LABELS, UNKNOWN_GROUP, WHITELIST_GROUPS
from .guards import guards_for, impact_for
from .masking import MASK, USER_ONLY_SETTING_KEYS, is_secret_key
from .models import (
    BOM,
    MAX_FILE_DIAGNOSTIC_KEYS,
    MAX_UNKNOWN_KEYS,
    ConfigGroupReport,
    ConfigItem,
    ConfigReport,
    ConfigSource,
    EnvFileReport,
    EnvScan,
    LayerMap,
    RoutingPoolsReport,
    RoutingPoolView,
    UnknownKeyReport,
)
from .sources import _solve


def _resolve_source(field_lower: str, layers: LayerMap) -> ConfigSource:
    """最后写入者（系统环境变量 > 项目 .env > 全局 .env > 默认值）。"""
    for source in (ConfigSource.SYSTEM_ENV, ConfigSource.PROJECT_ENV, ConfigSource.GLOBAL_SETTING):
        if field_lower in layers[source]:
            return source
    return ConfigSource.DEFAULT


def _item_notes(
    field_lower: str, layers: LayerMap, scans: dict[ConfigSource, EnvScan], active: tuple[ConfigSource, ...]
) -> tuple[str, ...]:
    """该键在两层 ``.env`` 里的诊断（重复 / 空值 / 未解析 / BOM 前缀 / 行内注释）。

    ``active`` 是**真正参与归属**的层：整体被降级摘掉的层不再产逐项诊断（否则文件里每个键都会被
    标成「未解析」，把响应级的那一条 ``project_env_invalid`` 稀释成噪声）。
    """
    notes: list[str] = []
    for source in (ConfigSource.PROJECT_ENV, ConfigSource.GLOBAL_SETTING):
        if source not in active:
            continue
        suffix = source.value
        values = layers[source]
        if f"{BOM}{field_lower}" in values:
            notes.append(f"bom_prefixed_in_{suffix}")
        scan = scans[source]
        if not scan.readable:
            continue
        as_written = scan.name_by_lower.get(field_lower)
        if as_written is None:
            # 文件里没有该键（键名被 BOM 前缀污染的情形已在上面的分支单独标注）。
            continue
        if values.get(field_lower) == "":
            # 空值行被接受成了一个空串（str 字段）——生效值确实是空的，如实标注。
            notes.append(f"empty_in_{suffix}")
            continue
        if field_lower not in values:
            # 声明了却没进层：空值（被当作未提供）或写法不受支持（如 export 之外的怪形式）。
            notes.append(f"empty_in_{suffix}" if as_written in scan.blank_keys else f"ineffective_in_{suffix}")
            continue
        if as_written in scan.duplicate_keys:
            notes.append(f"duplicate_in_{suffix}")
        if as_written in scan.inline_comment_keys:
            notes.append(f"inline_comment_in_{suffix}")
    return tuple(dict.fromkeys(notes))


def routing_report(settings: Settings) -> RoutingPoolsReport:
    """``ROUTING_POOLS`` 的**有效**结果（T8）：复用 ``Settings.routing_pool_map``（既有解析器）。

    「声明了但被忽略的条目」= 原始 JSON 里的条目名减去生效集合——只做**诊断**用的浅层 JSON 读取，
    绝不参与取值（取值与生效判据都来自既有解析器，它与运行期同源）。
    """
    raw = settings.routing_pools
    specs = settings.routing_pool_map
    payload: object | None
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, TypeError):
        payload = None
    declared = tuple(str(entry) for entry in payload) if isinstance(payload, dict) else ()
    return RoutingPoolsReport(
        declared_entries=declared,
        effective=tuple(
            RoutingPoolView(
                entry=entry,
                tiers=dict(spec.tiers),
                roles=dict(spec.roles),
                default=spec.default,
                keywords=dict(spec.keywords),
            )
            for entry, spec in specs.items()
        ),
        ignored_entries=tuple(entry for entry in declared if entry not in specs),
        invalid_json=bool(raw.strip()) and not isinstance(payload, dict),
    )


def _build_item(
    env_key: str,
    *,
    values: dict[str, Any],
    layers: LayerMap,
    scans: dict[ConfigSource, EnvScan],
    active: tuple[ConfigSource, ...],
    bom_stripped_head: str | None,
    routing: RoutingPoolsReport | None = None,
) -> ConfigItem:
    """装配一条配置项（值一律来自 ``Settings`` 快照）。"""
    field_lower = env_key.lower()
    secret = is_secret_key(env_key)
    source = _resolve_source(field_lower, layers)
    classification = classify(env_key)
    writable = classification.writable
    reason = classification.reason
    if writable and source is ConfigSource.SYSTEM_ENV:
        # 系统环境变量提供 ⇒ 改 .env 不生效（覆盖不了进程环境），因此不可写（AC2）。
        writable, reason = False, "system_env"
    notes = list(_item_notes(field_lower, layers, scans, active))
    if bom_stripped_head is not None and bom_stripped_head.lower() == field_lower:
        notes.append("bom_stripped_in_project_env")
    routing_view = routing if env_key == "ROUTING_POOLS" else None
    if routing_view is not None:
        if routing_view.invalid_json:
            notes.append("routing_pools_invalid")
        if routing_view.ignored_entries:
            notes.append("routing_pools_entries_ignored")
    configured = source is not ConfigSource.DEFAULT
    return ConfigItem(
        key=env_key,
        group=classification.group,
        value=None if secret else values.get(field_lower),
        source=source,
        writable=writable,
        read_only_reason=reason,
        is_secret=secret,
        configured=configured,
        masked=MASK if secret and configured else None,
        guards=guards_for(env_key),
        impact=impact_for(env_key),
        notes=tuple(notes),
        routing=routing_view,
    )


def _bounded(names: tuple[str, ...], limit: int = MAX_FILE_DIAGNOSTIC_KEYS) -> tuple[tuple[str, ...], bool]:
    """把**来自文件内容**的诊断列表截到上界（响应体不随 ``.env`` 膨胀）。"""
    return names[:limit], len(names) > limit


def _unknown_keys(
    scans: dict[ConfigSource, EnvScan], known: frozenset[str]
) -> tuple[tuple[UnknownKeyReport, ...], tuple[str, ...]]:
    """未知 / 拼错的键（AC5）+ 是否发生截断。

    依据**行级扫描**（文件里写了什么）而不是「参与归属的层」：整层因降级被摘掉时，文件里的未知键
    仍必须报出来——否则 AC5 的诊断恰在最需要它的输入上消失（评审发现·镜头二③）。两个门：文件不可读
    或**非 UTF-8**（键名会被替换字符污染）时不报。注意 ``EnvSettingsSource`` 会**丢掉**未知的系统
    环境变量（实测），因此系统层不可能贡献未知键。

    ``USER_ONLY_SETTING_KEYS`` **只对用户层生效**：它们是合法的用户级键（如 WS token），但写在
    项目 ``.env`` 里既不生效也不合法——那条路径必须照常报成未知键，否则「写错地方」会被诊断
    面板当作正常键吞掉（与「凭证只认用户级文件」的立场一致）。
    """
    found: list[UnknownKeyReport] = []
    for source, scan in scans.items():
        if not scan.readable or not scan.encoding_ok:
            continue
        allowed = known | USER_ONLY_SETTING_KEYS if source is ConfigSource.GLOBAL_SETTING else known
        for name in scan.declared_keys:
            if name.lower() in allowed:
                continue
            found.append(UnknownKeyReport(key=name, source=source))
    truncated = len(found) > MAX_UNKNOWN_KEYS
    return tuple(found[:MAX_UNKNOWN_KEYS]), (("unknown_keys_truncated",) if truncated else ())


def _group_reports(
    *,
    values: dict[str, Any],
    layers: LayerMap,
    scans: dict[ConfigSource, EnvScan],
    active: tuple[ConfigSource, ...],
    bom_stripped_head: str | None,
    routing: RoutingPoolsReport | None = None,
) -> tuple[ConfigGroupReport, ...]:
    """按声明式分组装配全部条目（每个 env 键恰好落在一组）。

    同一个 ``id`` 可以出现在多条 :class:`ConfigGroupSpec` 上（如 ``outbound`` / ``run_semantics``
    各有一条显式键行与一条模式行）——这里按 ``id`` **合并成一组**，标签取首次出现的那个。
    """
    labels: dict[str, str] = {}
    members: dict[str, list[str]] = {}
    for spec in (*WHITELIST_GROUPS, *EXCLUSION_GROUPS, UNKNOWN_GROUP):
        labels.setdefault(spec.id, spec.label)
        members.setdefault(spec.id, [])
    for env_key in sorted(key.upper() for key in Settings.model_fields):
        members[classify(env_key).group].append(env_key)
    reports: list[ConfigGroupReport] = []
    for group_id, group_label in labels.items():
        keys = members[group_id]
        if not keys:
            continue
        items = tuple(
            _build_item(
                env_key,
                values=values,
                layers=layers,
                scans=scans,
                active=active,
                bom_stripped_head=bom_stripped_head,
                routing=routing,
            )
            for env_key in keys
        )
        reports.append(ConfigGroupReport(id=group_id, label=group_label, items=items))
    return tuple(reports)


def build_config_report(
    project_env_file: str | Path, *, global_setting_file: str | Path | None = GLOBAL_SETTING_FILE
) -> ConfigReport:
    """求解一个项目的有效配置（值 + 来源 + 可写性 + 诊断）。

    ``project_env_file`` 必须是**该项目**的 ``<工作区根>/.env`` 绝对路径（脊柱 I2：相对 ``.env``
    会按进程 cwd 解析，多项目下必然错位）。成本**实测**中位 14.0 ms/次（n=7，探针 ``epic50_probe14``；
    其中 ``Settings`` 构造 4.5 ms、行级扫描 0.13 ms、``model_dump`` 0.16 ms，其余为三个来源实例），
    响应约 38 KB——面板请求量级下**不引入缓存**：以指纹为键的缓存本身也要读文件，而陈旧快照与
    「生效语义 = 下一次 run」（I10）冲突。
    """
    project = Path(project_env_file).expanduser()
    setting_file = Path(global_setting_file).expanduser() if global_setting_file is not None else None
    scans = {
        ConfigSource.PROJECT_ENV: scan_env_file(project),
        ConfigSource.GLOBAL_SETTING: scan_setting_md(setting_file),
    }
    solved = _solve(setting_file, project)
    layers = solved.layers

    notes: list[str] = list(solved.notes)
    global_scan = scans[ConfigSource.GLOBAL_SETTING]
    if (
        ConfigSource.GLOBAL_SETTING not in solved.used
        and setting_file is not None
        and isinstance(global_scan, SettingMdScan)
        and global_scan.parse_error
    ):
        notes.append("user_setting_unparseable")
    project_scan = scans[ConfigSource.PROJECT_ENV]
    if not project_scan.exists:
        notes.append("project_env_missing")
    elif not project_scan.readable:
        notes.append("project_env_unreadable")
    if project_scan.has_bom:
        notes.append("project_env_bom_stripped")
    if bom_prefixed_keys(layers):
        notes.append("bom_prefixed_keys")

    values: dict[str, Any] = solved.settings.model_dump(mode="json")
    known = frozenset(key.lower() for key in Settings.model_fields)
    unknown, unknown_notes = _unknown_keys(scans, known)
    notes.extend(unknown_notes)
    duplicate_keys, duplicates_truncated = _bounded(project_scan.duplicate_keys)
    blank_keys, blanks_truncated = _bounded(project_scan.blank_keys)
    if duplicates_truncated or blanks_truncated:
        notes.append("file_diagnostics_truncated")
    bom_stripped_head = project_scan.declared_keys[0] if project_scan.has_bom and project_scan.declared_keys else None

    return ConfigReport(
        field_count=len(Settings.model_fields),
        groups=_group_reports(
            values=values,
            layers=layers,
            scans=scans,
            active=solved.used,
            bom_stripped_head=bom_stripped_head,
            routing=routing_report(solved.settings),
        ),
        env_file=EnvFileReport(
            path=str(project),
            exists=project_scan.exists,
            readable=project_scan.readable,
            fingerprint=project_scan.fingerprint,
            has_bom=project_scan.has_bom,
            line_count=project_scan.line_count,
            duplicate_keys=duplicate_keys,
            blank_keys=blank_keys,
        ),
        unknown_keys=unknown,
        labels=dict(LABELS),
        notes=tuple(dict.fromkeys(notes)),
    )
