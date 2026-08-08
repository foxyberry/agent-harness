---
name: recovery-data-outside-its-subject
description: 무언가를 복구하려고 남기는 기록은 그 "무언가" 바깥에 둘 것 — 대상이 사라질 때 기록도 같이 사라지면 무의미
type: project
---

삭제·소실을 **복구하기 위한 기록**은 복구 대상 **안에** 두지 않는다. 대상이 사라지는 순간
기록도 함께 사라져서, 정작 필요한 시점에 없다.

**Why:** 2026-08-07 PR #80 에서 Codex 교차검토가 P1 으로 잡았다.

worktree 가 제거된 뒤에도 "이 경로가 어느 저장소였나"를 되짚으려고 alias 캐시를 만들었는데,
저장 위치를 `project_dir/.claude/.cache/` 로 잡았다. `project_dir` 자체가 linked worktree 일 때
캐시가 **그 worktree 안에** 생긴다 → worktree 를 지우면 캐시도 같이 사라진다. 게다가 본체
체크아웃은 다른 캐시를 읽어 서로 못 본다. 되짚으려고 만든 기록이 되짚어야 할 순간에 없는 셈.

`<repo>/.git/agent-harness/` (git 공통 디렉터리) 로 옮겨 해결했다. 모든 worktree 가 공유하고,
worktree 제거와 무관하게 살아남고, 커밋 대상도 아니다.

**How to apply:**
- 캐시·인덱스·alias 를 설계할 때 **"복구 대상이 사라질 때 이 기록도 사라지나?"** 를 먼저 묻는다.
- worktree 관련 상태는 `git rev-parse --git-common-dir` 아래 둔다 — 모든 worktree 공유 +
  삭제 내성 + 커밋 제외가 동시에 만족된다.
- 세션·트랜스크립트·임시 폴더처럼 **수명이 짧은 것에 대한 기록**은 그것보다 오래 사는
  곳에 둔다.
- 관측된 적 없는 대상은 **추정하지 말고 포기**한다. 이름이나 경로 모양으로 짐작하면 오탐이
  나고, 잘못된 복구가 없는 복구보다 나쁘다.

관련: [[committed-artifact-env-leak]], [[engine-data-separation]]
