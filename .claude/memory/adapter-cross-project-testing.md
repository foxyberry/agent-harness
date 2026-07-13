---
name: adapter-cross-project-testing
description: 어댑터(Claude/Codex) 동작은 harness repo 밖 별도 프로젝트에서 검증 — dev 설치가 버그를 가림
type: project
---

Claude/Codex 어댑터의 런타임 동작(핸드오프 저장 경로 등)은 **agent-harness repo 밖의 별도
프로젝트**에서 검증해야 한다. dev 설치는 marketplace 가 repo 를 직접 참조 → 스킬 폴더가
harness repo 안에 있어, cwd 기준 로직(git-toplevel 등)이 항상 repo 를 찾아 **cross-project
버그를 가린다**.

**Why:** 이슈 #3 에서 handoff.py 의 cwd 의존 버그가 dogfooding 내내 안 잡혔다 — 스킬 폴더가
repo 안이라 우연히 동작. 실제 사용자 설치(스킬=플러그인 캐시=repo 밖)에서만 깨졌다.

**How to apply:** 어댑터 스크립트 동작 검증 시, `git init` 한 scratch 프로젝트를 만들고 스킬
스크립트를 repo 밖 경로에 복사해 그 scratch 를 대상으로 실행하라. "harness 안에서 동작"은
증명이 아니다. 관련: [[skill-command-examples]], [[build-drift]].
