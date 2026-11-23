#!/usr/bin/env python3
"""new-goal —— 为 /loop 的 v7 契约起一个 goal 骨架。

产物（全部落在 <root>/docs/ 下，本仓 <root> = 仓库根）：
  docs/<goal-id>/brief.md          需求原文 + 派生需求段（Step 01 填）
  docs/<goal-id>/progress.md       编排状态唯一真源（骨架）
  docs/<goal-id>/tickets/tickets.toml   票树入口（空，[[epic]] 由 Step 04 写）
  
  docs/current                     current 指针（默认写；--no-current 跳过）

本脚本只建骨架，**不写任何 Requirements/entry**——那是 Step 04/06 的产物，需人工审批。
不依赖 _bmad/、不读任何 BMad 配置。

用法：
  python new-goal.py <goal-id> [--title 标题] [--request 需求原文]
                     [--root DIR] [--no-current] [--force]
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

GOAL_ID = re.compile(r'^[a-z0-9][a-z0-9-]*$')

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'

BRIEF_TEMPLATE = 'BRIEF.md'
PROGRESS_TEMPLATE = 'PROGRESS.md'


def render_template(name: str, **fields) -> str:
    """按 templates/<name> 渲染骨架：单遍替换命名占位符，替换进来的文本不再被扫描。"""
    path = TEMPLATES / name
    if not path.is_file():
        raise SystemExit(f'template not found: {path}')
    text = path.read_text(encoding='utf-8')
    if not fields:
        return text
    pattern = re.compile(r'\{(' + '|'.join(map(re.escape, fields)) + r')\}')
    return pattern.sub(lambda m: str(fields[m.group(1)]), text)

TICKETS = """# 票树入口：[[epic]] 表由 Step 04 写入，表顺序即构建顺序。
# 每个 epic 建 tickets/epic-<slug>/ 文件夹（薄 epic 带 refined: false），
# entry 清单写该 epic 的 tickets/tickets.toml，plan 与它同级。
"""


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / 'AGENTS.md').is_file() or (p / 'docs').is_dir():
            return p
    return start


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('goal_id')
    ap.add_argument('--title', default='')
    ap.add_argument('--request', default='<用户原话，逐字冻结；不要改写或美化>')
    ap.add_argument('--root', default='')
    
    ap.add_argument('--no-current', action='store_true', help='不写 docs/current 指针')
    ap.add_argument('--force', action='store_true', help='目标目录已存在时仍写入（覆盖骨架文件）')
    a = ap.parse_args()

    if not GOAL_ID.match(a.goal_id):
        print(json.dumps({'error': f'invalid goal-id: {a.goal_id} (expect ^[a-z0-9][a-z0-9-]*$)'},
                         ensure_ascii=False))
        return 2

    root = Path(a.root).resolve() if a.root else find_root(Path.cwd())
    docs = root / 'docs'
    goal = docs / a.goal_id
    if goal.exists() and not a.force:
        print(json.dumps({'error': f'goal dir exists: {goal}', 'hint': 'use a new id (-a/-b…) or --force'},
                         ensure_ascii=False))
        return 1

    title = a.title or a.goal_id
    today = date.today().isoformat()
    created = []

    goal.mkdir(parents=True, exist_ok=True)
    (goal / 'tickets').mkdir(exist_ok=True)

    for name, body in (
        ('brief.md', render_template(BRIEF_TEMPLATE, title=title, request=a.request)),
        ('progress.md', render_template(
            PROGRESS_TEMPLATE, goal_id=a.goal_id, title=title, today=today,
            initiative=f'initiative-{a.goal_id}')),
    ):
        p = goal / name
        p.write_text(body, encoding='utf-8', newline='\n')
        created.append(str(p.relative_to(root)))

    tt = goal / 'tickets' / 'tickets.toml'
    tt.write_text(TICKETS, encoding='utf-8', newline='\n')
    created.append(str(tt.relative_to(root)))

    

    if not a.no_current:
        docs.mkdir(parents=True, exist_ok=True)
        cur = docs / 'current'
        cur.write_text(a.goal_id + '\n', encoding='utf-8', newline='\n')
        created.append(str(cur.relative_to(root)))

    print(json.dumps({
        'root': str(root),
        'goal_dir': str(goal),
        'created': created,
        'next': [
            f'python .heagent/skills/bmad-agent-po/scripts/tickets.py status {goal}',
            'Step 01: 读 brief.md，把「总结的需求」写进 Derived Requirements',
            'Step 04: 写 tickets/tickets.toml 的 [[epic]] + 各 epic 薄文件（需人工审批）',
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
