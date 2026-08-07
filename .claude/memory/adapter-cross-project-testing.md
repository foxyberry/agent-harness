---
name: adapter-cross-project-testing
description: 어댑터 동작과 공개 설치는 repo·인증·캐시를 격리해 검증 — 개발 환경이 버그를 가림
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
증명이 아니다.

marketplace 설치·업데이트 검증은 기존 설치와 GitHub 권한을 재사용하지 않도록 격리한다.

- Codex: 빈 `CODEX_HOME`과 빈 `GIT_CONFIG_GLOBAL`에서 marketplace add/install/upgrade 실행
- Claude Code: 빈 `CLAUDE_CONFIG_DIR`과 빈 `GIT_CONFIG_GLOBAL` 사용
- 익명 공개 설치를 검증할 때는 `GIT_SSH_COMMAND=/usr/bin/false`로 SSH를 실패시켜 HTTPS fallback 확인
- 설치 성공 메시지만 보지 말고 source URL, 플러그인 버전, enabled 상태와 설치 캐시를 확인

**Why:** 공개 전환 이슈 #71에서 현재 머신의 SSH 권한과 기존 플러그인 캐시가 외부 사용자 설치
조건을 가릴 수 있었다. 빈 설정과 인증 실패를 강제한 뒤에야 공개 HTTPS 설치를 독립적으로 증명했다.

관련: [[skill-command-examples]], [[build-drift]].
