---
name: prettier-guard
description: prettier --write 전에 main 기준 non-clean 파일을 찾아 제외하고, check-only/safe-write 후보 명령을 advisory 로 제안
context: fork
allowed-tools: Bash, Read
argument-hint: "선택: --base-ref REF / --json / 파일..."
---

# prettier-guard

`prettier --write` 가 기존 main 에서도 깨끗하지 않은 긴 데이터/테스트 파일을 전체 재정렬하지
않도록, 변경 파일을 먼저 분류한다. **advisory-only** 다. 실제 `prettier --write` 는 자동 실행하지 않는다.

## 언제 쓰나

- 구현 후 formatter 를 돌리기 전
- 긴 fixture, schema, generated-like 데이터 파일을 건드렸을 때
- 리뷰 가능한 diff 를 유지해야 해서 전체 파일 포맷을 피하고 싶을 때

## 실행

```
python3 scripts/prettier_guard.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>"
```
> ⚠️ 위 `scripts/prettier_guard.py` 는 이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로다. 그 스킬 폴더로 cd 한 뒤 실행하되, `--project-dir` 에 지금 작업 중인 사용자 프로젝트의 실제 절대경로를 넘겨라. 이 인자 없이는 플러그인 캐시를 검사할 수 있다.

옵션:
- `--base-ref REF` — clean 여부를 판단할 기준 ref(기본: `origin/HEAD`)
- `--prettier "CMD"` — prettier 명령 직접 지정
- `--config PATH` — 설정 파일 직접 지정(기본: `.claude/memory/prettier-guard.json`)
- `--json` — 사람용 리포트 대신 JSON 출력
- `--fail-on-protected` — protected 파일이 있으면 exit 2(CI/check 용)
- `파일...` — 명시 파일만 검사(생략 시 base 대비 변경 파일 + staged/unstaged 파일)

## 리포트가 보는 것

- safe prettier 대상: 기준 ref 에서 prettier-clean 이거나 새 파일인 변경 파일
- protected non-clean 대상: 기준 ref 에서 이미 prettier-clean 이 아니거나 설정에 등록된 파일
- skipped: prettier 대상 확장자가 아니거나 설정에서 제외된 파일
- 후보 명령: safe 파일만 대상으로 한 `prettier --check`, `prettier --write`

## 프로젝트 설정

선택 설정 파일: `.claude/memory/prettier-guard.json`

```json
{
  "knownNonClean": [
    "apps/api/src/services/writing.ts",
    "packages/shared/src/schemas/exam.test.ts"
  ],
  "exclude": [
    "dist/**",
    "generated/**"
  ],
  "extensions": [".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".yaml", ".yml"]
}
```

## 하지 않는 것

- `prettier --write` 자동 실행 금지
- protected 파일 전체 포맷 금지
- formatter 결과를 자동 커밋하지 않음
