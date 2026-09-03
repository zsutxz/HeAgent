---
title: '浣?/goal next 鎺ㄨ繘澹版槑寮忓伐浣滄祦妫€鏌ョ偣'
type: 'bugfix'
created: '2026-09-03'
status: 'completed'
baseline_commit: '9060e6cfa41d7aaee32d61c3032848da53bad1dc'
review_loop_iteration: 0
context:
  - 'E:\\AI\\HeAgent\\AGENTS.md'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** 澹版槑寮忓伐浣滄祦涓甫 `checkpoint: true` 鐨勬楠ゅ畬鎴愬悗锛岀姸鎬佷細姝ｇ‘鎸佷箙鍖栦负 `waiting_user`銆傜敤鎴锋墽琛?`/goal resume` 鍚庯紝褰撳墠瀹炵幇鍙皢鐘舵€佹敼鍥?`pending` 鑰屼笉鍚姩涓嬩竴姝ラ锛屼粛椤婚澶栨墽琛?`/goal next`锛涜繖杩濊儗浜嗘樉寮忕‘璁ゅ悗缁х画鎵ц鐨勫伐浣滄祦鎵胯锛屽苟浣库€滅户缁紑鍙戔€濆仠鍦ㄦ鏌ョ偣銆傛渶鍚庝竴涓楠や篃浼氳妫€鏌ョ偣瑕嗙洊涓虹瓑寰呯姸鎬侊紝杩濊儗宸ヤ綔娴佲€滄渶鍚庝竴姝ラ獙鏀堕€氳繃鍗冲畬鎴愨€濈殑缁堟€佺害瀹氥€?
**Approach:** 淇濈暀涓棿妫€鏌ョ偣鐨勬樉寮?`/goal resume` 纭杈圭晫銆傛垚鍔熸仮澶嶅悗锛屽湪鍚屼竴 CLI 鍛戒护鍐呰皟鐢ㄧ幇鏈夌殑涓€姝ユ帹杩涜矾寰勶紝浣垮畠鎭板ソ鎵ц涓嬩竴姝ラ锛沗/goal next` 瀵?`waiting_user` 浠嶆樉鎬ф彁绀哄厛鎭㈠銆俁unner 浠呭湪鍚庣画姝ラ瀛樺湪鏃舵妸瀹屾垚缁撴灉杞负妫€鏌ョ偣绛夊緟锛屾渶缁堟楠ゅ繀椤讳繚鎸佸畬鎴愭€併€?
## Boundaries & Constraints

**Always:** 淇濈暀 `WorkflowRunner` 鐨勪竴姝ラ鎵ц銆佹寔涔呭寲鍜屾鏌ョ偣璇箟锛涗粎鏈夊悗缁楠ょ殑妫€鏌ョ偣鎵嶅彲杩涘叆 `waiting_user`锛涘彧閫氳繃鐜版湁 `WorkflowRunner.resume()` 杞崲鐘舵€侊紱鎭㈠涓庝笅涓€姝ラ鎵ц蹇呴』鎸佹湁鏃㈡湁 `_goal_auto_lock`锛涗换浣曟墽琛岀粨鏋滈兘蹇呴』鐢辩幇鏈?`run_step()` 璺緞鎸佷箙鍖栵紱澶辫触鍜岄樆濉炵姸鎬佷笉寰楄鑷姩缁曡繃銆?
**Ask First:** 涓嶉€傜敤銆?
**Never:** 涓嶅彇娑?`checkpoint: true` 鐨?`waiting_user` 鐘舵€侊紱涓嶈 `/goal next` 鎴栬嚜鍔?cron 鎵ц缁曡繃妫€鏌ョ偣锛涗笉淇敼 `WorkflowRunner` 鏍稿績鐘舵€佹満銆佸伐浣滄祦璧勬簮鏍煎紡鎴栭仐鐣?GOAL.md 璺緞銆?
## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| 妫€鏌ョ偣缁х画 | 鍓嶄竴姝ュ畬鎴愶紝`checkpoint: true`锛岀姸鎬佷负 `waiting_user` 涓旀椿鍔ㄦ楠ゅ凡鍓嶇Щ | `/goal resume` 鎭㈠鍚庢伆濂借繍琛屼竴涓笅涓€姝ラ | 浣跨敤鐜版湁妫€鏌ョ偣鎸佷箙鍖栬矾寰?|
| 妫€鏌ョ偣鎷掔粷 | 鍓嶄竴姝ュ畬鎴愬悗鐢ㄦ埛鎵ц `/goal next` | 涓嶈繍琛屾楠わ紝鎻愮ず鎵ц `/goal resume` | 淇濇寔妫€鏌ョ偣绛夊緟鐘舵€?|
| 涓诲姩鏆傚仠 | 鐢ㄦ埛鎵ц `/goal pause` 鍚庣姸鎬佷负 `waiting_user` | `/goal resume` 鎭㈠鍚庢伆濂借繍琛屼竴涓椿鍔ㄦ楠?| 鎭㈠鎴栨墽琛屽け璐ユ椂淇濈暀鏄炬€х姸鎬佷笌鍘熷洜 |
| 闈炵瓑寰呯姸鎬?| 鐘舵€佷负 `pending` 鎴栧凡瀹屾垚 | `/goal resume` 涓嶈皟鐢ㄦ楠ゆ墽琛?| 杈撳嚭鏃犻渶鎭㈠鎴栧凡瀹屾垚鎻愮ず |
| 鏈€缁堟鏌ョ偣 | 鏈€鍚庢楠ゅ甫 `checkpoint: true` 涓旀垚鍔?| 宸ヤ綔娴佷负 `completed`锛屼笉瑕佹眰 `/goal resume` | 鐢辩幇鏈夌粓鎬佹寔涔呭寲璺緞璁板綍 |

</frozen-after-approval>

## Code Map

- `src/heagent/cli.py` -- 澹版槑寮?`/goal` 鍛戒护鍒嗗彂銆佹仮澶嶅拰涓€姝ユ帹杩涜竟鐣岋紱`_goal_declarative_pause_resume()` 褰撳墠浠呮仮澶嶅苟鎸佷箙鍖栫姸鎬侊紝`_goal_declarative_dispatch()` 褰撳墠鏈湪 `resume` 鍚庢帹杩涖€?- `src/heagent/engine/workflow_runner.py` -- `WorkflowRunner.run_step()` 鍦ㄦ鏌ョ偣瀹屾垚鍚庢帹杩?`active_step` 骞惰涓?`WAITING_USER`锛沗resume()` 鏄厑璁哥殑鐘舵€佹仮澶嶅叆鍙ｏ紝涓嶈兘淇敼鍏舵牳蹇冨绾︺€?- `src/heagent/engine/workflow_runner.py` -- 鏈€缁堟楠ゅ綋鍓嶄篃浼氳妫€鏌ョ偣鏉′欢瑕嗙洊涓?`WAITING_USER`锛涘簲浠ユ槸鍚︿粛鏈変笅涓€姝ラ浣滀负妫€鏌ョ偣绛夊緟鐨勫墠缃潯浠躲€?- `tests/test_goal_declarative_workflow.py` -- CLI 绔埌绔０鏄庡紡宸ヤ綔娴佽鐩栵紝褰撳墠娴嬭瘯椤绘墜宸ユ墽琛?`pause`銆乣resume` 鍚庢墠楠岃瘉 `next`銆?- `tests/test_workflow_runner.py` -- Runner 绾ф鏌ョ偣涓庢樉寮忔仮澶嶈涔夌殑鍥炲綊淇濇姢锛屽簲淇濇寔涓嶅彉銆?
## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/cli.py` -- 璁╂仮澶嶈緟鍔╁嚱鏁拌繑鍥炴槸鍚﹀疄闄呮仮澶嶏紝鍙湁鎴愬姛鎭㈠鎵嶄氦鐢辫皟鐢ㄦ柟鎵ц涓嬩竴姝ラ锛涗繚鐣欏凡瀹屾垚銆佹棤闇€鎭㈠鍜屾寔涔呭寲澶辫触鏃剁殑鐜版湁鏄炬€ф彁绀恒€?- [ ] `src/heagent/cli.py` -- 鍦?`/goal resume` 鍒嗘敮鍐呮寔鏈?`_goal_auto_lock`锛屾垚鍔熸仮澶嶅苟鎸佷箙鍖栧悗璋冪敤涓€娆?`_goal_declarative_advance()`锛沗next`銆乣run`銆乧ron 鍜屽叾浠栧懡浠や繚鎸佹鏌ョ偣绛夊緟琛屼负銆?- [ ] `src/heagent/engine/workflow_runner.py` -- 闄愬埗妫€鏌ョ偣绛夊緟浠呴€傜敤浜庨潪鏈€缁堝凡瀹屾垚姝ラ锛岀‘淇濇渶鍚庝竴姝ュ嵆浣垮０鏄庢鏌ョ偣涔熸寔涔呭寲涓?`completed`銆?- [ ] `tests/test_goal_declarative_workflow.py` -- 灏?CLI 娴佺▼鏀逛负鍦ㄧ涓€妫€鏌ョ偣鍚庝粎鎵ц `/goal resume`锛屾柇瑷€绗簩姝ラ鎭板ソ鎵ц涓€娆°€佸墠姝ヨ緭鍑轰粛琚彁渚涗笖妫€鏌ョ偣 ID 鏃犻噸澶嶏紱鏂板妫€鏌ョ偣鍚庣殑 `/goal next` 涓嶈繍琛屽瓙浼氳瘽鐨勮鐩栥€?- [ ] `tests/test_workflow_runner.py` -- 瑕嗙洊鍗曟鎴栨湯姝ュ甫妫€鏌ョ偣鏃剁洿鎺ュ畬鎴愶紝闃叉缁堟€佽妫€鏌ョ偣鐘舵€佽鐩栥€?
**Acceptance Criteria:**
- Given 涓€涓袱姝ュ伐浣滄祦鐨勭涓€姝ュ凡鍦ㄧ敤鎴锋鏌ョ偣瀹屾垚, when 鐢ㄦ埛鎵ц `/goal resume`, then 浠呯浜屾杩愯涓€娆′笖寰楀埌绗竴姝ヨ緭鍑恒€?- Given 涓€涓瓑寰呯敤鎴风‘璁ょ殑妫€鏌ョ偣, when 鐢ㄦ埛鎵ц `/goal next`, then 涓嶆墽琛屽瓙浼氳瘽涓旀彁绀轰娇鐢?`/goal resume`銆?- Given 鐢ㄦ埛鏄庣‘鏆傚仠涓€涓湭瀹屾垚宸ヤ綔娴? when 鐢ㄦ埛鎵ц `/goal resume`, then 浠呭綋鍓嶆楠よ繍琛屼竴娆°€?- Given 鐘舵€佷负 `pending` 鎴栧伐浣滄祦宸插畬鎴? when 鐢ㄦ埛鎵ц `/goal resume`, then 涓嶈皟鐢ㄥ瓙浼氳瘽骞惰緭鍑哄綋鍓嶇姸鎬佺殑鏄炬€ф彁绀恒€?- Given 鏈€鍚庝竴涓０鏄庢鏌ョ偣鐨勬楠ゆ垚鍔? when Runner 鎸佷箙鍖栫粨鏋? then 宸ヤ綔娴佺姸鎬佷负 `completed` 涓旀棤闇€鎭㈠鍛戒护銆?
## Spec Change Log

## Design Notes

灏嗘仮澶嶅悗鐨勬帹杩涢檺鍒跺湪 CLI 鐨?`resume` 鍛戒护鍙繚鐣欎綆灞傜姸鎬佹満閫氱敤锛歊unner 浠嶅彧琛ㄨ揪鍜屾寔涔呭寲鐘舵€侊紝鑰屽懡浠ゅ眰灏嗘樉寮忔仮澶嶇‘璁よ浆鎹负涓€娆′笅涓€姝ラ鎵ц銆傛仮澶嶈緟鍔╁嚱鏁板繀椤诲悜璋冪敤鏂规姤鍛婃槸鍚︾湡姝ｅ彂鐢熸仮澶嶏紝閬垮厤宸插畬鎴愩€佹棤闇€鎭㈠鎴栨寔涔呭寲澶辫触鏃舵剰澶栨墽琛屻€?
## Verification

Completed: `pytest --basetemp=.pytest_tmp_local/goal-resume-final tests/test_goal_declarative_workflow.py tests/test_workflow_runner.py -q` (15 passed); Ruff checks passed for all changed Python files. The full suite also exposed one unrelated pre-existing Windows hook timeout failure in `tests/test_hooks.py::TestHookTimeout::test_timeout_blocks_and_returns_promptly`.

**Commands:**
- `pytest tests/test_goal_declarative_workflow.py tests/test_workflow_runner.py -q` -- expected: all declarative CLI and runner checkpoint contracts pass.
- `ruff check src/heagent/cli.py tests/test_goal_declarative_workflow.py` -- expected: no lint errors.

