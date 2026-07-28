---
name: review-ledger
description: 여러 라운드 PR 리뷰의 finding을 ID·상태·근거로 추적하고 재검수 순서와 PR 댓글용 요약을 생성
context: fork
allowed-tools: Bash, Read, Grep
argument-hint: "PR 번호 또는 finding 갱신 요청"
---

# review-ledger

PR 리뷰가 여러 라운드로 이어질 때 findings를 문장 기억에 맡기지 않고 로컬 원장으로 관리한다.
항상 **기존 open finding 검증을 먼저** 하고, 그 다음 신규 문제를 탐색한다.

## 시작

```bash
python3 scripts/review_ledger.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>" init --pr 123
python3 scripts/review_ledger.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>" reviewer --pr 123 --name Claude --thread "<thread-id>"
```
> ⚠️ `scripts/review_ledger.py` 는 이 스킬 폴더 기준 상대경로다. 스킬 폴더에서 실행하고 `--project-dir` 에 사용자 프로젝트 절대경로를 넘겨라.

원장은 사용자 프로젝트의 `.claude/.cache/review-ledger/pr-123.json`에 저장된다. `init`이
로컬 `.git/info/exclude`에 `.claude/.cache/`를 등록하므로 git에는 커밋되지 않는다.
`handoff-save`는 현재 브랜치 원장의 open findings와 reviewer/thread를 커밋 핸드오프에
자동 포함한다.

## finding 등록과 갱신

```bash
python3 scripts/review_ledger.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>" add --pr 123 --severity P2 \
  --file src/example.ts --line 42 --claim "실패 경로에서 ready가 갱신되지 않는다" \
  --evidence "rg -n 'setReady' src/example.ts" --reviewer Claude

python3 scripts/review_ledger.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>" update --pr 123 F-001 --status fixed \
  --evidence "python3 -m unittest tests.test_example"
```

- 상태: `open`, `fixed`, `rejected`, `withdrawn`
- severity: `P1`, `P2`, `P3`
- “X가 없다” 같은 **부재 주장**은 문구로 자동 감지하며 `--evidence` 검색 명령이 없으면
  등록이 실패한다. 휴리스틱이 잘못 잡은 경우에만 `--not-absence`로 명시 해제한다.
- 새 리뷰 라운드를 시작할 때 `round --pr 123`을 실행한다. open finding이 남아 있으면
  먼저 재검수를 요구하며, 확인 후 계속할 때만 `--acknowledge-open`을 붙인다.

## PR 댓글용 요약

```bash
python3 scripts/review_ledger.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>" show --pr 123
```

출력은 Open/Resolved 표와 append-only 라운드 이력이 포함된 고정 Markdown이라 PR 댓글이나
handoff 근거로 그대로 쓸 수 있다. `show --pr 123 --json`은 자동화용이다.
