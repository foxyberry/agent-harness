---
name: squash-merge-consequences
description: 이 저장소는 squash merge — git 조상 기반 판정(branch --merged)이 무력화되고, stacked PR 은 base 머지 후 rebase 필요
type: project
---

이 저장소는 PR 을 **squash merge** 한다. PR 의 커밋들이 main 에 새 커밋 하나로 눌려
들어가므로, **원래 브랜치 tip 은 main 의 조상이 되지 않는다.** 여기서 두 가지가 파생된다.

**1. `git branch --merged` 가 아무것도 못 잡는다**

머지 여부는 git 조상 관계가 아니라 **PR head 기준**으로 판정해야 한다
(`gh pr list --state all --json headRefName,state`). 브랜치 삭제도 `-d` 는 거부되므로 `-D` 가 필요하다.

**2. stacked PR 은 base 가 머지되면 rebase 해야 한다**

base PR 위에 쌓은 PR 의 base 를 main 으로 바꾸기만 하면, base PR 의 **옛 커밋이 딸려
들어간다**(squash 결과와 patch-id 가 다르므로). `git rebase --onto origin/main <옛 base>` 로
자기 커밋만 옮긴 뒤 base 를 변경한다.

**Why:** 2026-08-07 실측.
- `/merge-cleanup` 이 "로컬 merged 브랜치 0개 / worktree 0개"로 오탐했다. 실제로는 로컬 23개
  중 22개, worktree 3개 전부가 정리 대상이었다. 같은 스킬의 원격 브랜치 섹션은 PR API 를 써서
  제대로 잡았다 — 판정 근거가 섹션마다 갈려 있던 게 원인 (이슈 #78).
- PR #77 을 #74 위에 쌓았는데 #74 가 squash 머지되자, base 만 바꾸면 #74 의 옛 커밋이
  섞이는 상태가 됐다. 사용자가 "리베이스 해야 하는거 아니야?"를 먼저 지적했다.

**How to apply:**
- 브랜치·worktree 정리 후보를 판정할 때 `git branch --merged` 를 쓰지 마라. PR API 로 판정한다.
- stacked PR 은 base 머지 직후 `git rebase --onto origin/main <옛 base 브랜치>` → force-push →
  `gh pr edit --base main`. 바꾸기 전에 `git diff origin/main --name-only` 로 **의도한 파일만**
  들었는지 확인한다.
- 삭제 전 복구 가능성을 확인한다: merged PR head 는 main 에 내용이 있고, closed PR head 도
  GitHub 이 `refs/pull/<N>/head` 를 영구 보관한다. **PR 기록이 아예 없는 로컬 브랜치만
  진짜로 사라진다** — 이것만 따로 확인받아라.

관련: [[build-drift]]
