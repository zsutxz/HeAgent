#!/usr/bin/env python3
"""selfcheck —— /loop v7 票树链路的自检。

在隔离目录里起一个临时 goal，真跑一遍
`new-goal` → Step04(epic) → Step06(entry) → Step07(plan/mark) → pull → move，
再对 `tickets.py` 的 status / next / find / mark / pull / move 六个子命令逐个断言。

不改 `docs/`、不改任何源码；默认把临时树留在 `.heagent/tmp/<repo>/v7-selfcheck/`（`--clean` 删除）。

退出码：0 全通过；1 有断言失败。
用法：
  python .heagent/skills/loop/scripts/selfcheck.py [--workdir DIR] [--clean]
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[4]                      # .heagent/skills/loop/scripts/selfcheck.py → 仓库根
TICKETS_PY = REPO / '.heagent/skills/bmad-agent-po/scripts/tickets.py'
NEW_GOAL_PY = HERE.parent / 'new-goal.py'

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = '') -> None:
    (PASS if ok else FAIL).append(name)
    print(('PASS  ' if ok else 'FAIL  ') + name + (f'   [{detail}]' if detail and not ok else ''))


def tickets(*args: str):
    out = subprocess.run([sys.executable, str(TICKETS_PY), *args],
                         cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    try:
        return out.returncode, json.loads(out.stdout or '{}')
    except json.JSONDecodeError:
        return out.returncode, {'_raw': out.stdout[:300], '_err': out.stderr[:300]}


def write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding='utf-8', newline='\n')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default=str(REPO / '.heagent/tmp' / REPO.name / 'v7-selfcheck'))
    ap.add_argument('--clean', action='store_true', help='跑完删除临时树')
    a = ap.parse_args()

    work = Path(a.workdir).resolve()
    if work.exists():
        shutil.rmtree(work)
    goal_id = f'probe-{int(time.time())}'

    # ---------- new-goal ----------
    out = subprocess.run([sys.executable, str(NEW_GOAL_PY), goal_id,
                          '--title', 'v7 selfcheck probe', '--request', 'selfcheck',
                          '--root', str(work)],
                         cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    created_ok = out.returncode == 0
    check('new-goal 建骨架成功', created_ok, out.stderr[:200])
    goal = work / 'docs' / goal_id
    check('brief.md 存在', (goal / 'brief.md').is_file())
    check('progress.md 存在', (goal / 'progress.md').is_file())
    check('tickets/tickets.toml 存在', (goal / 'tickets/tickets.toml').is_file())
    check('docs/current 指针写入', (work / 'docs/current').is_file())

    # 幂等保护
    dup = subprocess.run([sys.executable, str(NEW_GOAL_PY), goal_id, '--root', str(work)],
                         cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    check('重复建同一 goal 被拒', dup.returncode != 0 and 'exists' in dup.stdout)

    # ---------- 空树可读 ----------
    code, st = tickets('status', str(goal))
    check('空树 status 成功且 0 票', code == 0 and st.get('counts', {}).get('total') == 0)

    # ---------- Step 04 / 06 / 07 ----------
    write(goal / 'tickets/tickets.toml',
          '[[epic]]\nid = 1\nslug = "epic-core"\ntitle = "Probe core"\n'
          'description = "selfcheck epic"\ncovers = ["R1"]\n')
    epic = goal / 'tickets/epic-core'
    write(epic / 'epic-core.md',
          '---\ntype: epic\ntitle: "Probe core"\nparent: ' + goal_id +
          '\ncovers: [R1]\nrefined: true\n---\n\n# Probe core\n\n## Requirements\n\n'
          'R1 (parent R1): selfcheck.\n')
    write(epic / 'tickets/tickets.toml',
          '[[entry]]\nid = 1\ntype = "story"\ntitle = "Probe story"\n'
          'description = "selfcheck entry"\nverify = "status shows 1.1"\n'
          'covers = ["R1"]\nafter = []\nhitl = false\nrisk = "low"\n')
    write(epic / 'tickets/story-1-probe-plan.md',
          '---\ntitle: "Probe story"\ntype: feature\nticket: 1\ncreated: "2026-11-15"\n'
          'status: draft\nbaseline_revision: "unset"\nroute: oneshot\nrisk: low\n---\n\n'
          '# Probe story\n\n## Tasks & Acceptance\n\n- noop\n\n## Verification\n\n- none\n')

    code, st = tickets('status', str(goal))
    t = (st.get('tickets') or [{}])[0]
    check('status 读到 1.1', code == 0 and t.get('ref') == '1.1')
    check('初始 status = draft', t.get('status') == 'draft')

    code, nx = tickets('next', str(goal))
    check('next 列出 1.1 为 ready_to_start',
          code == 0 and [r['ref'] for r in nx.get('ready_to_start') or []] == ['1.1'])

    code, mk = tickets('mark', str(goal), '1.1', 'in-progress')
    check('mark → in-progress', code == 0 and mk.get('status') == 'in-progress')
    code, mk = tickets('mark', str(goal), '1.1', 'built')
    check('mark → built', code == 0 and mk.get('status') == 'built')

    code, fd = tickets('find', str(goal), '1.1')
    check('find 返回 plan 且文件存在',
          code == 0 and Path(fd.get('plan') or '').is_file())
    check('find 回读 status = built', fd.get('status') == 'built')

    # ---------- pull（例外口径：epic 目录 + 纯 entry id）----------
    code, pl = tickets('pull', str(epic), '1')
    check('pull <epic 目录> <id> 成功', code == 0 and bool(pl.get('file')))

    # ---------- move ----------
    write(goal / 'tickets/tickets.toml',
          '[[epic]]\nid = 1\nslug = "epic-core"\ntitle = "Probe core"\n'
          'description = "selfcheck epic"\ncovers = ["R1"]\n\n'
          '[[epic]]\nid = 2\nslug = "epic-target"\ntitle = "Probe target"\n'
          'description = "selfcheck target"\ncovers = ["R1"]\n')
    target = goal / 'tickets/epic-target'
    write(target / 'epic-target.md',
          '---\ntype: epic\ntitle: "Probe target"\nparent: ' + goal_id +
          '\ncovers: [R1]\nrefined: true\n---\n\n# Probe target\n')
    write(target / 'tickets/tickets.toml', '# empty\n')
    code, mv = tickets('move', str(epic), '1', str(target))
    check('move 1.1 → 2.1', code == 0 and mv.get('ref') == '2.1')
    code, st = tickets('status', str(goal))
    check('move 后 status 只剩 2.1', code == 0 and
          [x['ref'] for x in st.get('tickets') or []] == ['2.1'])

    print()
    print(f'PASS={len(PASS)}  FAIL={len(FAIL)}')
    if FAIL:
        print('failed:', FAIL)
    if a.clean:
        shutil.rmtree(work, ignore_errors=True)
        print('workdir cleaned:', work)
    else:
        print('workdir kept:', work)
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
