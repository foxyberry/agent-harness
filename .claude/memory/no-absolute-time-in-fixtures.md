---
name: no-absolute-time-in-fixtures
description: 최근성 창(cutoff)을 보는 코드의 테스트 fixture 에 절대 시각을 박지 말 것 — 날짜가 지나면 코드 변경 없이 CI 가 깨진다
type: project
---

세션 로그 탐색은 **최근 N일**만 본다 — `handoff.py` 의 `_recent_codex_rollouts(days=30)`,
`_has_project_codex_rollout(days=30)`, `history` 의 `--since` 파싱. 이런 코드의 테스트
fixture 에 `os.utime` 으로 **절대 epoch 을 박으면 안 된다.** `time.time()` 기준 상대값으로
만들고, 테스트가 실제로 주장하는 **상대 순서**(A 가 B 보다 오래됨)만 고정한다.

**Why:** `tests/test_handoff_transcript_scope.py` 가 `self.now = 1_785_000_000.0`
(2026-07-26)을 박아뒀다. 2026-08-22 에는 11일 전이라 30일 창 안이었고 CI 가 초록이었다.
2026-08-31 에 36일이 되면서 fixture 가 창 밖으로 밀려나, **커밋 하나 없이** main 의
unit test 5건이 깨졌다. 원인 커밋이 없으니 diff 를 봐도 안 보이고, 마지막 초록 커밋과
비교해도 소용이 없다.

이 실패는 리뷰로 안 잡힌다. 작성 시점에는 통과하고, 통과하는 채로 머지되고, 아무도
건드리지 않은 날 깨진다. `tests/test_fw_live_session.py` 에도 같은 모양이 있었다 —
아직 안 깨졌을 뿐 같은 폭탄이었다(#128 에서 함께 고침).

**How to apply:**

```python
# ❌ 날짜가 지나면 스스로 깨진다
self.now = 1_785_000_000.0

# ✅ 창 안에 머무르고, 상대 순서는 그대로
self.now = time.time() - 86400.0        # 어제
_write_rollout(..., self.now - 3600)    # 그보다 1시간 더 오래됨
```

- 새 테스트가 mtime·타임스탬프를 만들 때 **항상 `time.time()` 기준**으로 잡는다.
- 창 밖을 **일부러** 시험하는 테스트라면 그것도 상대값으로 만든다
  (`time.time() - 40*86400`) — 그래야 `days` 기본값이 바뀌어도 의도가 유지된다.
- 날짜 디렉터리(`~/.codex/sessions/2026/08/11/`)는 고정해도 된다. 탐색이 `os.walk` 로
  전체 트리를 훑고 **mtime 만** 보기 때문이다. 걸리는 건 언제나 mtime 쪽이다.

관련: [[build-drift]]
