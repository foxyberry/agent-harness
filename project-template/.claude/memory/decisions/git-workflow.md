---
name: git-workflow
description: 이 프로젝트 git 작업 규칙 (예시 — 네 프로젝트에 맞게 교체)
type: project
---

<예시 파일이다. routes.json 의 `contains: ["git"]` 규칙이 이 파일을 주입한다 — 내용을 네 팀 규칙으로 교체하라.>

- main 직접 푸시 금지 — 브랜치 + PR.
- 커밋 전 사용자 승인. 머지 후 `/feedback-review` · `/memory-update` 회고.

**Why:** 리뷰 없이 main 에 들어간 변경이 롤백 비용을 만든다.
**How to apply:** git 관련 작업(커밋·머지·푸시) 전에 이 규칙을 우선 적용한다.
