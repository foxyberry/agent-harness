---
name: code-quality
description: 이 프로젝트 코드 품질 규칙 (예시 — 네 프로젝트에 맞게 교체)
type: feedback
---

<예시 파일이다. routes.json 의 `*.kt` 규칙이 이 파일을 주입한다 — 내용을 네 프로젝트 규칙으로 교체하라.>

- Kotlin `!!` 금지 — `requireNotNull` 또는 `?: return` 사용.
- 컬렉션 누적은 `var` + 루프 대신 `fold`/`associate`/`sumOf` 우선.

**Why:** NPE 가 런타임까지 숨는 사고가 반복됐다.
**How to apply:** 편집 전 주입되는 이 메모리를 확인하고, reflection 훅 경고를 무시하지 않는다.
