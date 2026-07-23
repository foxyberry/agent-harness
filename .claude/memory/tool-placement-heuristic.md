---
name: tool-placement-heuristic
description: 새 훅·도구 배치 결정 = 범용 엔진이면 하네스 core / 취향·규약 의존이면 개인 ~/.claude(내 습관) 또는 repo 커밋(팀 공유). 훅은 core 에 넣지 말 것
type: feedback
---

새 훅·스킬·도구를 어디에 둘지 결정할 때 매번 재도출하지 말고 이 기준을 쓴다.

| 성격 | 위치 | 이유 |
|---|---|---|
| **범용 엔진** (툴·프로젝트 무관, 데이터로 동작) | 하네스 **core/** → build.sh → 어댑터 배포 | 설치자 모두에게 재사용. 단 "무엇을"은 하드코딩 말고 프로젝트 데이터로([[engine-data-separation]]) |
| **내 개인 습관** (이 유저와 일하는 방식, 브랜치 규약 의존) | 개인 **`~/.claude/hooks`** + settings | 내 모든 repo 즉시 적용, 커밋 불필요, 팀 공유 안 됨 |
| **팀 규칙** (팀원·타 머신도 따라야) | 각 **repo 에 커밋** (`.claude/hooks` + settings, `$CLAUDE_PROJECT_DIR` 상대참조 / 또는 git `.githooks`) | 클론하는 모두가 따름. 넣을 repo 마다 작업 |

**Why:** 2026-07-23 PR-이슈 연결 훅(그리고 그 전 서명 훅)에서 사용자가 매번 "하네스에 넣을지,
각 repo 에 넣을지 고민된다"를 반복해 물었다. 결정 기준이 없어 그때그때 재논의됨.

**How to apply:**
- **하네스 core 판단 기준**: 브랜치명 규약·팀 취향에 의존하면 core 아님(범용성 깨짐). 게다가 하네스 훅은
  현재 Claude 전용(Codex 훅 defer) — 훅은 웬만하면 core 에 넣지 말고 개인/ repo 로.
- **개인 vs repo 커밋**: "나만 지키면 됨" → 개인. "팀원·다른 머신도 강제" → repo 커밋(서명 훅 방식).
- **애매하면 사용자에게 한 번 물어** 개인/repo/하네스 중 고르게 한다(반복 갈림길이라 확인 값어치 있음).
- 병렬 작업 중인 repo 에 커밋할 땐 **git worktree 로 비침습** 처리(다른 AI 워킹트리 안 건드림).

관련: [[engine-data-separation]], [[build-drift]], [[branch-name-issue-number]]
