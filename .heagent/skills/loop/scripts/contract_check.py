#!/usr/bin/env python3
"""contract_check —— /loop 契约文本的静态自检（纯 stdlib，只读）。

校验四类问题，任一命中即退出码 1：
1. 契约正文中反引号引用的仓库内路径必须真实存在；
2. 陈旧口径不得出现在契约正文中（大写 `Docs/`、`_he-output/works`、`sprint-status`、
   `--envelope`、`_bmad-output/initiative-`）。被否定语境（不产/不写/废弃/旧口径…）包住的行放行；
3. `tickets.py` 的子命令示例必须带显式 goal 目录，不得写成 `mark <ref>` 这类裸写法；
4. Step 01 至 Step 08 小节齐全，且 `templates/` 下每个模板都被契约或脚本引用。

用法：python .heagent/skills/loop/scripts/contract_check.py
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
PKG = HERE.parents[1]                 # .heagent/skills/loop
REPO = HERE.parents[4]                # 仓库根（.heagent/skills/loop/scripts → 上溯 4 级）
CONTRACT_FILES = [PKG / 'SKILL.md', PKG / 'workflow.md', PKG / 'templates' / 'STORY.md',
                  *sorted((PKG / 'references').glob('*.md'))]
NEGATION = re.compile(r'不产|不写|不要|废弃|旧口径|已删|已废|不再|不得|禁止|作废|退役|不建|无 ?sprint')

STALE = [
    (re.compile(r'(?<![\w.])Docs/'), '大写 `Docs/` 状态根（应为 `docs/`）'),
    (re.compile(r'_he-output/works'), '`_he-output/works`（goal 已迁到 docs/）'),
    (re.compile(r'sprint-status'), '`sprint-status`（v7 无 sprint）'),
    (re.compile(r'--envelope'), '`--envelope`（脚本已删该参数）'),
    (re.compile(r'_bmad-output/initiative-'), '`_bmad-output/initiative-`（v7 票树在 goal 目录内）'),
]

TICKETS_BARE = re.compile(r'tickets\.py\s+(mark|find|pull|status|next|move)\s+<ref>')
PATH_TOKEN = re.compile(r'`((?:\.heagent|scripts|templates|references)/[^`\s<>]+)`')
STEP_HEAD = re.compile(r'^## Step (0[1-8]):', re.M)


def path_exists(token: str) -> bool:
    """`scripts/`、`templates/`、`references/` 相对 loop 包；`.heagent/...` 相对仓库根。"""
    if '*' in token:
        return any(PKG.glob(token)) or any(REPO.glob(token))
    if token.startswith('references/'):
        # 本包章节文件，或角色包的 references（如 `bmad-agent-po` 的 `references/slice.md`）
        return (PKG / token).exists() or any((PKG.parent).glob(f'*/{token}'))
    if token.startswith(('scripts/', 'templates/')):
        return (PKG / token).exists() or (REPO / token).exists()
    return (REPO / token).exists()


def main() -> int:
    problems: list[str] = []

    for path in CONTRACT_FILES:
        rel = path.relative_to(REPO).as_posix()
        if not path.is_file():
            problems.append(f'{rel}: 契约文件缺失')
            continue
        lines = path.read_text(encoding='utf-8').splitlines()
        for n, line in enumerate(lines, 1):
            loc = f'{rel}:{n}'
            ctx = lines[n - 2] if n >= 2 else ''
            if not (NEGATION.search(line) or NEGATION.search(ctx)):
                for pat, why in STALE:
                    if pat.search(line):
                        problems.append(f'{loc}: 陈旧口径 {why}')
            for m in TICKETS_BARE.finditer(line):
                problems.append(f'{loc}: tickets.py {m.group(1)} 缺显式 goal 目录')
            for m in PATH_TOKEN.finditer(line):
                if not path_exists(m.group(1)):
                    problems.append(f'{loc}: 引用路径不存在 `{m.group(1)}`')


    wf = PKG / 'workflow.md'
    if wf.is_file():
        steps = STEP_HEAD.findall(wf.read_text(encoding='utf-8'))
        missing = [f'0{i}' for i in range(1, 9) if f'0{i}' not in steps]
        if missing:
            problems.append(f'workflow.md: 缺少步骤小节 Step {", ".join(missing)}')

    tpl = PKG / 'templates'
    if tpl.is_dir():
        text = '\n'.join(p.read_text(encoding='utf-8') for p in CONTRACT_FILES if p.is_file())
        text += '\n' + (PKG / 'scripts' / 'new-goal.py').read_text(encoding='utf-8')
        for f in sorted(tpl.glob('*.md')):
            if f.name not in text:
                problems.append(f'templates/{f.name}: 契约与脚本均未引用（死模板）')

    if problems:
        print(f'FAIL  {len(problems)} 处')
        for p in problems:
            print('  ' + p)
        return 1
    print('PASS  契约文本通过静态检查（路径、陈旧口径、票树显式目录、Step 01-08、模板引用）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
