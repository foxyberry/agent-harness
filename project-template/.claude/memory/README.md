# .claude/memory — 프로젝트 메모리 (데이터 층)

이 디렉토리는 하네스 훅의 **데이터 층**이다. 엔진(스킬·훅)은 `agent-harness` 플러그인이
제공하고, "무엇을" 주입·경고할지는 여기 프로젝트별 파일이 정한다. 3층 구조의 "데이터=프로젝트" 경계.

## 설정 파일 (엔진이 읽는 것)

| 파일 | 읽는 훅 | 역할 | 없으면 |
|------|---------|------|--------|
| `routes.json` | memory-search (PreToolUse Edit/Write) | 편집 파일 → 주입할 메모리 매핑 | no-op (주입 없음) |
| `reflection-rules.json` | reflection (PostToolUse Edit/Write) | 새 코드 → 품질 경고 정규식 규칙 | 내장 TODO/FIXME 규칙만 |

두 예시 파일은 Kotlin/Spring 기준이다. **네 프로젝트 언어·규칙에 맞게 고쳐라.**

## 메모리 파일 (routes.json 이 가리키는 것)

`routes.json` 의 `memory` 항목이 가리키는 실제 지식 파일. 예: `patterns/code-quality.md`,
`decisions/git-workflow.md`. frontmatter(name/description/type) 를 가진 마크다운으로 쓰고,
`INDEX.md` 에 한 줄씩 등록한다(Codex 는 이 인덱스로 읽는다). `/memory-update` 스킬이 관리한다.

## _pending/ (자동 회고 초안)

`HARNESS_AUTO_REFLECT=1` 로 자동 회고를 켜면, reflect 잡이 세션 트랜스크립트를 분석해
승격 후보 초안을 `_pending/*.md` 에 쌓는다. `/memory-update` 로 검토·승격(또는 폐기)한다.
기본은 꺼져 있다 — 설치만으로 백그라운드 LLM 잡이 뜨지 않는다.

## 자동 회고 켜기 (opt-in)

```bash
export HARNESS_AUTO_REFLECT=1   # 머지 시 claude -p 로 회고 초안 자동 생성
```
백엔드는 `REFLECT_BACKEND`(claude|deepseek|ollama, 기본 claude) 로 고른다.
