# 技能资源读取 TOCTOU 威胁评估

## 结论

本评估结论为：**assessment only；当前不改变跨平台运行时语义**。`SkillPackage` 继续复用
`resolve_under_root`，该围栏能拒绝绝对路径、路径穿越和解析后越界的符号链接，但不能把“解析/检查”与
后续 `read_text()` 绑定为同一个 OS 文件身份。新增特征测试复现了检查后替换窗口，因此不得声称已完成
TOCTOU 防护。任何加固应另立实现 story。

## 影响面与威胁模型

`SkillPackage.read_entry()`、`read_step()`/`read_resource()` 以及目录辅助方法
`read_reference()`、`read_template()`、`read_asset()`、`read_script()` 都遵循
“解析路径 -> `is_file()` -> `read_text()`”。受影响资源包括入口、step、reference、template、asset 和
script。攻击者需要能够在同一进程检查之后、打开之前修改包目录项或其符号链接；这通常意味着包目录或
宿主文件系统已被并发写入者控制。技能内容和本地文件系统均应视为不可信。

当前控制是包根先 `resolve()`，资源通过 `resolve_under_root(resource, root)` 做 `strict=False` 解析，并以
`Path.is_relative_to(root)` 拒绝越界。控制对普通路径穿越和静态越界链接有效，但不持有 descriptor、目录句柄
或不可变快照，故无法覆盖检查后替换。

## 可重复证据

`tests/test_skill_packages_toctou.py` 通过 monkeypatch 在 `is_file()` 返回成功后立即替换资源，分别覆盖：

1. 已解析的普通资源在检查后被替换为新内容；
2. 符号链接解析得到的目标文件在使用前被替换为包外直接指向；

两项均读到包外内容，证明存在 check/use 窗口。测试只刻画现状，不改变生产行为；符号链接创建失败的
平台会显式 skip，并在测试报告中保留能力说明。

## 候选方案比较

| 方案 | 正确性条件 | 跨平台可行性 | 成本/兼容性 | 残余风险 |
| --- | --- | --- | --- | --- |
| descriptor-relative open（`openat`/`O_NOFOLLOW` 等） | 必须从受信目录句柄逐段打开，并按平台设置 no-follow 语义 | POSIX 较好；Windows 需专用 API，Python 抽象不统一 | 平台分支、句柄生命周期和 symlink 策略复杂；可能改变异常语义 | OS/文件系统差异、挂载和恶意进程仍需 OS 隔离 |
| directory handle / re-check | 打开父目录句柄并校验最终 identity，再从句柄读取 | POSIX 可行；Windows 语义不等价 | 需要额外 stat/句柄代码，异步封装与兼容性负担 | 校验策略错误或不支持句柄的 FS 仍有窗口 |
| copy/snapshot | 在受信导入边界原子复制后只读快照，并固定 hash/identity | 跨平台最好，适合 importer | 复制 I/O、磁盘空间和时机成本；已存在的攻击者可污染源 | 不能保护已被攻击者控制的现有包，且快照前仍有竞态 |
| OS sandbox | 在受限 namespace/容器中执行并限制 FS/进程权限 | 依赖部署平台与运维能力 | 最大部署成本，需外部后端；不是库内透明改动 | sandbox 配置错误或平台缺失；仍属 defense-in-depth |

## 决策与后续

当前选择保留既有路径围栏，仅交付测试和文档证据。没有一个候选方案在现有 Python 3.11、POSIX/Windows
组合上被证明既通用又不改变 API/异常语义；descriptor/句柄方案可作为未来专门 story，snapshot 方案更适合
可信导入边界，OS sandbox 才能处理 hostile filesystem/process context。后续实现必须单独定义 symlink 策略、
句柄/快照生命周期、错误映射和平台能力探测，并保留“非 OS 安全边界”的声明。
