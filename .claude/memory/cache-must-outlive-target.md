---
name: cache-must-outlive-target
description: 캐시·alias·인덱스 저장 위치 — worktree/세션/임시폴더처럼 사라질 것 안에 두지 말 것. worktree 상태는 .git 공통 디렉터리에
type: project
---

**캐시·alias·인덱스를 어디에 저장할지 정할 때 이 규칙을 쓴다.**

저장 위치를 고르기 전에 한 가지만 묻는다 — **"내가 기록하려는 대상이 사라질 때,
이 기록도 같이 사라지나?"** 그렇다면 위치가 틀렸다.

| 기록 대상 | 두면 안 되는 곳 | 둘 곳 |
|---|---|---|
| worktree 정보 | worktree 안 (`<worktree>/.claude/.cache/`) | `git rev-parse --git-common-dir` 아래 |
| 세션·트랜스크립트 정보 | 그 세션의 임시 폴더 | 프로젝트 또는 홈 |
| 임시 폴더 관련 상태 | 그 임시 폴더 안 | 그보다 오래 사는 곳 |

`git rev-parse --git-common-dir` 아래(`<repo>/.git/agent-harness/`)는 worktree 관련 상태의
기본값으로 삼을 만하다 — **모든 worktree 공유 + worktree 삭제 내성 + 커밋 제외**가
동시에 만족되는 유일한 위치다.

**Why:** 2026-08-07 PR #80 에서 Codex 교차검토가 P1 으로 잡았다.

worktree 가 제거된 뒤에도 "이 경로가 어느 저장소였나"를 되짚으려고 alias 캐시를 만들면서
저장 위치를 `project_dir/.claude/.cache/` 로 잡았다. 그런데 `project_dir` 자체가 linked
worktree 일 때 캐시가 **그 worktree 안에** 생긴다 → worktree 를 지우면 캐시도 같이 사라진다.
게다가 본체 체크아웃은 다른 캐시를 읽어 서로 못 본다. **되짚으려고 만든 기록이 되짚어야 할
바로 그 순간에 없는** 구조였다. `.git` 안으로 옮겨 해결했다.

혼자 보면 멀쩡해 보이는 게 이 버그의 특징이다 — 본체에서 테스트하면 통과한다.
worktree 를 `project_dir` 로 주는 경로를 따로 테스트해야 드러난다.

**How to apply:**
- 캐시 경로를 쓰는 코드를 짤 때 `project_dir` 이 **worktree 일 수 있다**고 가정한다.
- 관측된 적 없는 대상은 **추정하지 말고 포기**한다. 이름이나 경로 모양으로 짐작하면
  오탐이 나고, 잘못된 복구는 없는 복구보다 나쁘다.
- 테스트는 "본체에서 기록 → 본체에서 조회"가 아니라 **"worktree 에서 기록 → 그 worktree
  삭제 → 본체에서 조회"** 로 짠다. 앞엣것은 이 버그를 못 잡는다.

관련: [[committed-artifact-env-leak]], [[engine-data-separation]]
