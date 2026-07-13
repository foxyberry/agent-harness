---
name: plugin-release-updates
description: 사용자-facing 플러그인 배포는 버전 bump 와 업데이트 안내를 릴리스 단위로 관리
type: project
---

agent-harness 를 사용자에게 배포할 때는 로컬 dogfooding 과 사용자-facing 릴리스를 분리한다.
Codex 플러그인은 설치 캐시가 남기 때문에, 변경을 배포할 때 `plugins/codex/.codex-plugin/plugin.json`
버전을 올리고 README 의 업데이트 명령을 함께 유지한다.

**Why:** 같은 `0.1.0` 버전으로 계속 배포하면 사용자가 "내가 최신인가"를 확인하기 어렵고,
캐시 갱신을 위해 remove/add 같은 내부 절차를 반복 안내하게 된다. 일반 사용자는 자주
업데이트하지 않게 하고, 안정된 릴리스 단위로만 갱신하도록 해야 한다.

**How to apply:** 사용자-facing 변경을 릴리스할 때는 버전 bump 를 포함하고, README 에는 짧은
설치/업데이트 명령만 둔다. 현재 Codex 는 `plugin update` 가 없으므로 업데이트 안내는
`codex plugin marketplace upgrade foxyberry` 후 `codex plugin remove/add agent-harness@foxyberry`
흐름이다. 로컬 검증은 `./build.sh` 와 로컬 marketplace 로 dogfooding 하되, 그 절차를
일반 사용자 업데이트 방식처럼 안내하지 않는다.

**실증 (2026-07-12):** dev 설치(marketplace 가 repo 직접 참조)에서도 `codex plugin list` 의
VERSION 은 install 시점 스냅샷에 머문다 — 스킬 내용은 live 반영되지만 버전 표기는
remove/add 전까지 0.1.0 그대로였다. "버전 bump + remove/add 안내"가 필요한 이유의 실측 근거.
