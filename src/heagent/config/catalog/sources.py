"""四层来源求解器：pydantic-settings 单一来源 + 逐层失败降级。

自 ``heagent.config.catalog`` 单文件拆出（E3 绞杀者），行为零改动。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple

from pydantic_settings import DotEnvSettingsSource, EnvSettingsSource

from heagent.config import Settings
from heagent.config.user_settings import (
    SettingsError,
    UserMarkdownSettingsSource,
    read_setting_md,
    with_user_setting_layer,
)

from .models import BOM, ConfigSource, LayerMap

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("heagent.config.catalog")

# ── 四层来源求解 ──


class _BomTolerantDotEnvSource(DotEnvSettingsSource):
    """``DotEnvSettingsSource`` + **文件头 BOM** 容差（复用父类解析，不改值语义）。

    只剥「映射里第一个键」的 BOM：文件头 BOM 必然落在首个被解析的键上；文件**中部**的 BOM
    刻意保留（那种情况由 :func:`bom_prefixed_keys` 显式标注，而不是静默吞掉）。
    """

    def _read_env_file(self, file_path: Path) -> Any:
        """读单文件并剥掉**首个键**的 BOM（其余键原样保留，供 :func:`bom_prefixed_keys` 检出）。"""
        data = super()._read_env_file(file_path)
        head = next(iter(data), None)
        if isinstance(head, str) and head.startswith(BOM):
            clean = head[len(BOM) :]
            return {(clean if key is head else key): value for key, value in data.items()}
        return data


class _Solved(NamedTuple):
    """求解结果：有效 ``Settings`` + 参与归属的层 + 真正生效的 dotenv 层 + 降级说明。"""

    settings: Settings
    layers: LayerMap
    used: tuple[ConfigSource, ...]
    notes: tuple[str, ...] = ()


class _CatalogSettings(Settings):
    """只有 dotenv 源被换成 BOM 容差版的 ``Settings``：字段与校验**完全同源**。

    ``_ENV_IGNORE_EMPTY`` 决定「``KEY=``（空值）」算不算「该键被提供了」：**忠实口径**（``False``，
    与运行期默认一致）下空值以 ``''`` 进层，bool/int 字段随即校验失败（实测）；**容错口径**
    （``True``）下空值整条消失，等价于「未提供」。
    """

    _ENV_IGNORE_EMPTY: ClassVar[bool] = False

    @classmethod
    def settings_customise_sources(  # type: ignore[override]
        cls,
        settings_cls: type[Settings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        return (
            init_settings,
            env_settings,
            _BomTolerantDotEnvSource(
                settings_cls,
                env_file=getattr(dotenv_settings, "env_file", None),
                env_file_encoding=getattr(dotenv_settings, "env_file_encoding", "utf-8"),
                env_ignore_empty=cls._ENV_IGNORE_EMPTY,
            ),
            UserMarkdownSettingsSource(settings_cls, setting_file=cls._user_setting_file),
            file_secret_settings,
        )


class _LenientSettings(_CatalogSettings):
    """把 ``KEY=``（空值）当作「未提供」——只在忠实口径构造失败时启用（见 :func:`_solve`）。"""

    _ENV_IGNORE_EMPTY: ClassVar[bool] = True


def _dotenv_layer(path: Path | None, *, ignore_empty: bool) -> dict[str, str | None]:
    """某一层 ``.env`` 的原始键值（小写键）；不存在时**不读**，不可读时返回空（不抛）。"""
    if path is None or not path.is_file():
        return {}
    try:
        return dict(_BomTolerantDotEnvSource(Settings, env_file=path, env_ignore_empty=ignore_empty)())
    except Exception as exc:  # noqa: BLE001 - 单个层级不可用不得带崩整个面板（fail-soft）
        logger.warning("config layer %s is unusable: %s", path, exc)
        return {}


def _md_layer(path: Path | None) -> dict[str, str | None]:
    """用户层 ``setting.md`` 的原始键值（小写键）；不存在时不读，解析错时返回空（fail-soft，
    对齐 ``_dotenv_layer`` 的「单层不可用不得带崩面板」——错误由 ``scan_setting_md.parse_error``
    在响应级显性标注 ``user_setting_unparseable``，不在层求解里静默吞掉语义）。"""
    if path is None or not path.is_file():
        return {}
    try:
        return dict(read_setting_md(path))
    except SettingsError as exc:
        logger.warning("user setting layer %s is unusable: %s", path, exc)
        return {}


def _layer_map(setting_file: Path | None, project_file: Path, *, ignore_empty: bool) -> LayerMap:
    """两层文件（用户 md + 项目 .env）的原始内容（口径与同时求解的候选一致）。"""
    return {
        ConfigSource.GLOBAL_SETTING: _md_layer(setting_file),
        ConfigSource.PROJECT_ENV: _dotenv_layer(project_file, ignore_empty=ignore_empty),
    }


def _system_layer() -> dict[str, str | None]:
    """系统环境变量层（只见**已声明字段**的名字：``EnvSettingsSource`` 会丢掉未知变量）。"""
    try:
        return dict(EnvSettingsSource(Settings)())
    except Exception as exc:  # noqa: BLE001 - 同上
        logger.warning("system environment layer is unusable: %s", exc)
        return {}


def _solve(setting_file: Path | None, project_file: Path) -> _Solved:
    """求解有效 ``Settings`` 与参与归属的层（显式 ``[用户 md, 项目 .env]`` 路径，**不是**进程 cwd）。

    四级候选，逐级降级且**层与取值同步降级**（否则「来源说 project_env、值却来自用户层」会自相矛盾，AC8）：

    1. **忠实口径**（``env_ignore_empty=False``，与运行期默认一致）+ ``[项目 .env]`` + 用户层 md；
    2. **容错口径**（空值 = 未提供）——项目 ``.env`` 里存在 ``KEY=`` 时，bool/int 字段会让候选 1
       直接构造失败（实测，见探针 ``epic50_probe13``），此时按「空值即未提供」求解并点名该文件；
    3. **只留用户层**——项目 ``.env`` 的值非法（如 ``MAX_ITERATIONS=abc``）或编码不可解析；
    4. **一个文件层都不读**——用户层 ``setting.md`` 也不可用（语法错 / 不可读）。

    四级全败说明**系统环境变量**本身非法（进程级配置错误：运行时 ``Settings()`` 同样会失败），
    此时向上抛，不假装知道「有效值」。
    """
    project_files = [str(project_file)]
    attempts: tuple[tuple[type[_CatalogSettings], bool, list[str], tuple[ConfigSource, ...], tuple[str, ...]], ...] = (
        (
            with_user_setting_layer(setting_file, _CatalogSettings),
            False,
            project_files,
            (ConfigSource.GLOBAL_SETTING, ConfigSource.PROJECT_ENV),
            (),
        ),
        (
            with_user_setting_layer(setting_file, _LenientSettings),
            True,
            project_files,
            (ConfigSource.GLOBAL_SETTING, ConfigSource.PROJECT_ENV),
            ("project_env_blank_values",),
        ),
        (
            with_user_setting_layer(setting_file, _CatalogSettings),
            False,
            [],
            (ConfigSource.GLOBAL_SETTING,),
            ("project_env_invalid",),
        ),
        (
            with_user_setting_layer(None, _CatalogSettings),
            False,
            [],
            (),
            ("env_files_unavailable",),
        ),
    )
    last_error: Exception | None = None
    for settings_cls, ignore_empty, env_files, used, notes in attempts:
        try:
            # ``_env_file`` 是 pydantic-settings 的**运行时**参数（`BaseSettings.__init__` 从 kwargs
            # 里取走它），但 pydantic 的 mypy 插件按字段合成的 `__init__` 签名看不到它。
            settings = settings_cls(_env_file=env_files)  # type: ignore[call-arg]
        except Exception as exc:  # noqa: BLE001 - 降级而非带崩：候选非法 ⇒ 换下一档
            last_error = exc
            logger.warning("config solve tier %s failed: %s", used, exc)
            continue
        layers = _layer_map(setting_file, project_file, ignore_empty=ignore_empty)
        layers[ConfigSource.SYSTEM_ENV] = _system_layer()
        for source in (ConfigSource.GLOBAL_SETTING, ConfigSource.PROJECT_ENV):
            if source not in used:
                layers[source] = {}
        return _Solved(settings=settings, layers=layers, used=used, notes=notes)
    raise last_error if last_error is not None else RuntimeError("no configuration tier available")
