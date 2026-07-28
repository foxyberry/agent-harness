---
name: verify-regression
description: 새 테스트가 수정 전 source에서 실제로 실패하는지 임시 worktree로 검증하고 PR 댓글용 표로 분류
context: fork
allowed-tools: Bash, Read
argument-hint: "테스트 경로, source 경로, 테스트 실행 명령"
---

# verify-regression

버그 수정 PR의 새 테스트가 수정 전 코드에서 실제로 실패하는지 검증한다. 원본 워킹트리는
건드리지 않고 임시 worktree에서만 source를 base 버전으로 바꾼다.

## 실행

```bash
python3 scripts/verify_regression.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>" \
  --source hooks/useStudyProgress.ts \
  --command "npx vitest run {test}" \
  tests/useStudyProgress.test.ts
```
> ⚠️ `scripts/verify_regression.py` 는 이 스킬 폴더 기준 상대경로다. 스킬 폴더에서 실행하고 `--project-dir` 에 사용자 프로젝트 절대경로를 넘겨라.

옵션:
- 테스트 경로는 마지막에 하나 이상 지정한다. 각 경로를 별도 프로세스로 실행해 개별 분류한다.
- `--source`는 base로 되돌릴 구현 파일이다. 여러 개면 반복 지정한다.
- `--source`는 파일만 허용하며 디렉터리는 잘못된 판정을 막기 위해 거부한다.
- `--base merge-base`가 기본이며 `HEAD`와 `origin/main`의 merge-base를 사용한다.
- 아직 source 수정이 커밋 전이면 `--base HEAD`를 사용한다.
- 기본 브랜치가 다르면 `--base-ref origin/master`처럼 명시한다.
- `--command`에는 `{test}` placeholder가 반드시 있어야 한다. shell 파이프/리다이렉션은
  실행하지 않고 인자 배열로 안전하게 실행한다.
- `--timeout` 기본 300초, `--json`은 자동화용 출력이다.

## 판정

- pre-fix `FAIL` → `regression test (catches bug)`
- pre-fix `PASS` → `not regression (new-logic guard)`
- timeout → `inconclusive`

PASS 테스트를 삭제하라는 뜻이 아니다. 회귀 재현이 아니라 새 동작을 지키는 테스트라고 정확히
분류한다. 출력 Markdown 표는 PR 댓글에 그대로 사용하고, `/review-ledger` finding의
`--evidence`에도 명령과 결과를 남긴다.

## 복원 보장

현재 HEAD, 작업 diff, non-ignored untracked 파일을 `.claude/.cache/verify-regression/`
아래 임시 worktree에 복제한다. 먼저 수정 후 테스트가 PASS하는지 확인하고, 지정 source만
base로 바꾼 뒤 다시 실행한다. 수정 후 baseline 자체가 실패하면 회귀로 과대 보고하지 않고
`inconclusive`로 분류한다. 성공·실패·timeout·중단 시 `finally`에서 worktree를 제거한다.
실행 전후 원본 `git status --porcelain`이 다르거나 cleanup 경고/inconclusive가 있으면 exit 2다.

첫 실행은 임시 worktree가 실행 중 `git status`나 `git add -A`에 노출되지 않도록 사용자
저장소의 로컬 `.git/info/exclude`에 `.claude/.cache/`를 영구적으로 한 번 등록한다.
커밋되는 `.gitignore`는 수정하지 않으며, 같은 항목을 중복 추가하지 않는다.

임시 worktree는 프로젝트 아래에 있어 상위 `node_modules`를 찾을 수 있지만, `.env` 등
gitignore된 런타임 파일은 자동 복사하지 않는다. 필요한 설정은 테스트 명령에서 안전하게 주입한다.
