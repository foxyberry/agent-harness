# .claude/memory — 프로젝트 메모리 (데이터 층)

이 디렉토리는 하네스 훅의 **데이터 층**이다. 엔진(스킬·훅)은 `agent-harness` 플러그인이
제공하고, "무엇을" 주입·경고할지는 여기 프로젝트별 파일이 정한다. 3층 구조의 "데이터=프로젝트" 경계.

## 설정 파일 (엔진이 읽는 것)

| 파일 | 읽는 훅 | 역할 | 없으면 |
|------|---------|------|--------|
| `routes.json` | memory-search (PreToolUse 편집·Bash) | 편집 파일·셸 명령 → 주입할 메모리 매핑 | no-op (주입 없음) |
| `reflection-rules.json` | reflection (PostToolUse Edit/Write) | 새 코드 → 품질 경고 정규식 규칙 | 내장 TODO/FIXME 규칙만 |
| `prettier-guard.json` | prettier-guard skill | main 기준 non-clean 파일과 제외 glob 설정 | 기본 확장자만 검사 |

기본 활성 예시는 Kotlin/Spring 기준이다. **네 프로젝트 언어·규칙에 맞게 고쳐라.**

`reflection-rules.json`에는 기본 꺼짐인 `react-async-timing` 스타터 팩도 있다. React
프로젝트에서만 해당 pack의 `enabled`를 `true`로 바꿔 사용한다. 정규식 경고는 타이밍
위험 후보이므로 실제 scope를 확인하고 순서를 재현하는 테스트로 검증한다.

## 메모리 파일 (routes.json 이 가리키는 것)

`routes.json` 의 `memory` 항목이 가리키는 실제 지식 파일. 예: `patterns/code-quality.md`,
`decisions/git-workflow.md`. frontmatter(name/description/type) 를 가진 마크다운으로 쓰고,
`INDEX.md` 에 한 줄씩 등록한다(Codex 는 이 인덱스로 읽는다). `/memory-update` 스킬이 관리한다.

메모리에는 오래 유지할 **결정·제약·비자명한 패턴**만 둔다. 재개 체크포인트, WIP,
진행 중 PR과 다음 액션은 메모리가 아니다. 실제로 세션·툴·머신·사람을 전환할 때만
`/handoff-save` 로 인계한다. 줄 수·테스트 수·열린 PR 상태처럼 코드나 명령으로 다시
구할 수 있는 현재 값은 저장하지 않는다.

## _pending/ (자동 회고 초안)

`HARNESS_AUTO_REFLECT=1` 로 자동 회고를 켜면, reflect 잡이 세션 트랜스크립트를 분석해
승격 후보 초안을 `_pending/*.md` 에 쌓는다. `/memory-update` 로 검토·승격(또는 폐기)한다.
기본은 꺼져 있다 — 설치만으로 백그라운드 LLM 잡이 뜨지 않는다.

이 디렉토리의 `.gitignore` 가 `_pending/` 만 제외하므로 미승인 초안은 `git add .` 에
포함되지 않는다. 검토를 마쳐 상위 메모리나 `decisions/` 로 승격한 파일은 정상적으로
커밋할 수 있다.

이미 Git이 추적 중인 `_pending/` 파일에는 ignore 규칙이 소급 적용되지 않는다. 기존
프로젝트에서 초안을 커밋한 적이 있다면 내용을 검토한 뒤 Git 인덱스에서도 제거해야 한다.

## 자동 회고 켜기 (opt-in)

```bash
export HARNESS_AUTO_REFLECT=1   # 머지 시 claude -p 로 회고 초안 자동 생성
```
백엔드는 `REFLECT_BACKEND`(claude|deepseek|ollama, 기본 claude) 로 고른다.
