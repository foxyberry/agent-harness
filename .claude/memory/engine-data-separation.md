---
name: engine-data-separation
description: core/hooks는 generic 엔진, "무엇을" 은 프로젝트 데이터(.claude/memory/*.json). 하드코딩 금지
type: project
---

훅의 결합은 **제거가 아니라 재배치**한다. core/hooks 는 툴·프로젝트 무관 엔진이고,
"어떤 파일 → 어떤 메모리"(routes.json), "어떤 패턴 → 어떤 경고"(reflection-rules.json) 같은
구체 내용은 프로젝트의 `.claude/memory/*.json` 데이터가 정한다.

**Why:** 하드코딩(예: `.kt → code-quality.md`)을 core 에 두면 그 하나의 프로젝트에만 맞고
재사용이 깨진다. 엔진/데이터 분리가 하네스 3층 구조("데이터=프로젝트")의 실체다.

**How to apply:** core/hooks 에 언어·프로젝트 특정 로직(확장자, 파일명, 언어 규칙)을 넣지 마라.
새 매칭·규칙이 필요하면 엔진은 "설정 파일을 읽어 적용"하게만 하고, 실제 값은
project-template(예시) 또는 각 프로젝트 `.claude/memory/` 에 둔다. 관련: [[hooks-live-dir-gotcha]]
