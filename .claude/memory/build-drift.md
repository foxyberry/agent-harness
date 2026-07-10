---
name: build-drift
description: core/ 가 정본, 어댑터는 생성물. core 수정 후 항상 ./build.sh 하고 생성물까지 함께 커밋
type: project
---

`core/` 가 single source of truth 이고 `plugins/harness/`·`codex/` 는 build.sh 가 만드는 **생성물**이다.
core 를 고쳤으면 `./build.sh` 를 돌려 어댑터 재생성분까지 **같은 커밋**에 담아야 한다.

**Why:** CI(`.github/workflows/validate.yml`)가 build.sh 를 돌린 뒤 `git diff` 로 drift 를 검사한다 —
build 안 돌린 채 커밋하면 "core↔adapter 어긋남"으로 실패한다. 어댑터를 직접 손대면 다음 build 에서 덮인다.

**How to apply:** 어댑터(plugins/harness, codex)를 직접 편집하지 마라 — core 에서 고치고 build.sh.
SKILL.md 는 `{{RULES_FILE}}` 등 placeholder 로 쓰고 build.sh render 가 어댑터별 값으로 치환한다.
번들 스크립트는 어댑터 안에서 `${CLAUDE_PLUGIN_ROOT}`(Claude)로만 참조, `../` 금지.
