---
title: 'shell 杈撳嚭澶у皬涓婇檺涓庢埅鏂爣璁?
type: 'bugfix'
created: '2026-09-12'
status: 'done'
baseline_commit: '94d4c36abc6f33a6c239d7142c00df728fb765b5'
review_loop_iteration: 0
context:
  - 'E:/AI/HeAgent/docs/frame.md'
---

<frozen-after-approval reason="浜虹被纭鍚庣殑鎰忓浘涓嶅彲鐢卞疄鐜颁唬鐞嗘搮鑷慨鏀?>

## Intent

**Problem:** shell銆丳assthrough銆丗irejail 鍜?WinJob 璺緞浼氭妸瀛愯繘绋?stdout/stderr 鍏ㄩ噺鏀堕泦骞跺洖鐏屼笂涓嬫枃锛屾病鏈夌‘瀹氭€уぇ灏忎笂闄愶紱澶ц緭鍑哄彲鑳借€楀敖妯″瀷涓婁笅鏂囬绠椼€?
**Approach:** 鍦ㄥ叡浜粨鏋滄牸寮忓寲杈圭晫澧炲姞瀛楄妭绾ц緭鍑轰笂闄愶紝鎴柇鏃朵繚鐣欏彲璇婃柇鐨勯€€鍑虹爜鍜岄€氶亾鏍囩锛屽苟杩藉姞鏄庣‘鐨?`[truncated]` 鏍囪銆備繚鐣?stdout 灏鹃儴浠ラ伩鍏?SandboxSession 鐨?cwd/rc marker 鍥犳埅鏂涪澶便€?
## Boundaries & Constraints

**Always:** stdout 涓?stderr 閮藉彈闄愶紱榛樿涓婇檺涓烘瘡涓€氶亾 512 KiB锛涚粨鏋滀粛鍖呭惈 `exit_code=`銆乣stdout:`銆乣stderr:`锛涙埅鏂爣璁版槑纭彲琚祴璇曞拰璋冪敤鏂硅瀵燂紱UTF-8 瑙ｇ爜缁х画浣跨敤鏇挎崲閿欒绛栫暐銆?
**Ask First:** 鏃犮€?
**Never:** 涓嶆敼鍙樺懡浠ゆ墽琛屻€佽秴鏃躲€佸彇娑堛€佹潈闄愭垨娌欑绛栫暐锛涗笉鎶婃埅鏂綋浣滄墽琛屽け璐ワ紱涓嶄慨鏀?file_read 宸叉湁鐨?offset/limit 濂戠害锛涗笉寮曞叆 tokenizer 渚濊禆銆?
## I/O & Edge-Case Matrix

| 鍦烘櫙 | 杈撳叆 / 鐘舵€?| 棰勬湡琛屼负 | 閿欒澶勭悊 |
|---|---|---|---|
| 姝ｅ父杈撳嚭 | 涓や釜閫氶亾鍧囦綆浜庝笂闄?| 鍘熸牱杩斿洖锛屼笉鍑虹幇 `[truncated]` | 鏃?|
| stdout 瓒呴檺 | stdout 澶т簬 512 KiB | stdout 琚檺鍒讹紝淇濈暀澶村熬骞惰拷鍔犳埅鏂爣璁帮紱stderr 姝ｅ父淇濈暀 | 涓嶆姏寮傚父 |
| stderr 瓒呴檺 | stderr 澶т簬 512 KiB | stderr 琚檺鍒跺苟杩藉姞鎴柇鏍囪 | 涓嶆姏寮傚父 |
| session marker | 澶?stdout 鍚庤拷鍔?`HEAGENT_CWD` marker | marker 浠嶅彲瑙ｆ瀽锛宑wd/鐪熷疄 rc 鍥炲～閫昏緫涓嶅洖褰?| 涓嶅洜鎴柇鏀瑰彉閫€鍑虹姸鎬?|

</frozen-after-approval>

## Code Map

- `src/heagent/tools/sandbox.py` -- `_format_result` 缁熶竴鏍煎紡鍖?stdout/stderr锛汸assthrough銆丗irejail銆乄inJob 鍧囩粡姝よ矾寰勮繑鍥炵粨鏋滐紱`SandboxSession` 渚濊禆杈撳嚭灏鹃儴 marker銆?- `tests/test_sandbox.py` -- Passthrough銆乥ackend 鍜?SandboxSession 鐨勮涓哄洖褰掓祴璇曪紝閫傚悎琛ュ厖杈圭晫杈撳嚭鏂█銆?- `tests/test_coverage_sandbox.py` -- fake subprocess 鐨?communicate/鍙栨秷/瓒呮椂瑕嗙洊锛岀‘璁ゆ柊澧炴牸寮忓寲閫昏緫涓嶇牬鍧忔竻鐞嗚矾寰勩€?
## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/tools/sandbox.py` -- 澧炲姞鍏变韩瀛楄妭涓婇檺涓庝繚鐣欏ご灏剧殑鎴柇鏍煎紡鍖?-- 闃叉 shell 缁撴灉鏃犵晫杩涘叆涓婁笅鏂囷紝鍚屾椂淇濈暀 session marker銆?- [x] `tests/test_sandbox.py` -- 澧炲姞 stdout/stderr 瓒呴檺銆佹爣璁板拰 marker 淇濈暀娴嬭瘯 -- 閿佸畾鐢ㄦ埛鍙濂戠害銆?
**Acceptance Criteria:**
- Given stdout/stderr 鍧囨湭瓒呰繃闄愬埗锛寃hen 浠讳竴 runner 瀹屾垚鍛戒护锛宼hen 杩斿洖鍐呭涓庣幇鏈夋牸寮忎竴鑷翠笖鏃犳埅鏂爣璁般€?- Given 浠讳竴閫氶亾瓒呰繃 512 KiB锛寃hen runner 鏍煎紡鍖栫粨鏋滐紝then 璇ラ€氶亾鐨勮繑鍥炲瓧鑺傛暟鍙楅檺銆佸寘鍚?`[truncated]`锛屼笖閫€鍑虹爜浠嶅彲瑙併€?- Given SandboxSession 鍛戒护杈撳嚭瓒呰繃闄愬埗骞跺湪灏鹃儴鍐欏叆 cwd/rc marker锛寃hen session 瑙ｆ瀽缁撴灉锛宼hen cwd 涓庣湡瀹為€€鍑虹爜浠嶈鏇存柊銆?
## Verification

**Commands:**
- `pytest tests/test_sandbox.py tests/test_shell.py` -- expected: all tests pass銆?- `ruff check src/heagent/tools/sandbox.py tests/test_sandbox.py` -- expected: no findings銆?
## Suggested Review Order

**杈撳嚭杈圭晫**

- 鍏变韩鏍煎紡鍖栧櫒闄愬埗姣忎釜杈撳嚭閫氶亾
  [`sandbox.py:117`](../../src/heagent/tools/sandbox.py#L117)

- 鎴柇淇濈暀灏鹃儴 marker
  [`sandbox.py:80`](../../src/heagent/tools/sandbox.py#L80)

**楠岃瘉瑕嗙洊**

- stdout 瓒呴檺骞朵繚鐣欏熬閮?  [`test_sandbox.py:1210`](../../tests/test_sandbox.py#L1210)

- SandboxSession marker 鍥炲綊
  [`test_sandbox.py:1231`](../../tests/test_sandbox.py#L1231)

