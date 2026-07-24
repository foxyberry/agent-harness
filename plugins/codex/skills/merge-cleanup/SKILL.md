---
name: merge-cleanup
description: PR merge/close 후 로컬 main 동기화, 병합 브랜치, 관련 이슈, worktree, untracked 잔여물 정리 후보를 advisory-only 리포트로 점검
context: fork
allowed-tools: Bash, Read
argument-hint: "선택: --repo owner/name / --recent-limit N / --json"
---

# merge-cleanup

PR merge/close 이후 사람이 반복적으로 하던 정리를 한 번에 점검한다.
**advisory-only** 다. 브랜치 삭제, 이슈 close, worktree remove 는 자동 실행하지 않고 후보 명령만 보여준다.

## 언제 쓰나

- PR 을 머지한 직후
- 로컬 기본 브랜치 fast-forward, 브랜치 삭제, worktree 잔여물, close 된 이슈 상태를 한 번에 확인하고 싶을 때
- 여러 툴/세션을 오가며 정리 상태를 놓쳤을 때

## 실행

```
python3 scripts/merge_cleanup.py --project-dir "<지금 작업 중인 사용자 프로젝트 절대경로>"
```
> ⚠️ 위 `scripts/merge_cleanup.py` 는 이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로다. 그 스킬 폴더로 cd 한 뒤 실행하되, `--project-dir` 에 지금 작업 중인 사용자 프로젝트의 실제 절대경로를 넘겨라. 이 인자 없이는 플러그인 캐시를 검사할 수 있다.

옵션:
- `--repo owner/name` — GitHub repo 를 명시(생략 시 `gh repo view` 로 추론)
- `--recent-limit N` — 최근 merged/closed PR 조회 수(기본 20)
- `--no-fetch` — 시작 시 `git fetch origin` 생략
- `--json` — 사람용 리포트 대신 JSON 출력

## 리포트가 보는 것

- 기본 브랜치 동기화: local `<default>` 와 `origin/<default>` 의 ahead/behind, fast-forward 가능 여부
- 로컬 merged 브랜치 삭제 후보: 기본 브랜치에 이미 병합된 로컬 브랜치
- 원격 브랜치 삭제 후보: 최근 merged/closed PR 의 head branch 가 아직 `origin/` 에 남아 있는 경우
- 관련 이슈 close 확인 후보: 최근 merged PR 의 `closingIssuesReferences`
- worktree 정리 후보: 이미 병합된 로컬 브랜치를 물고 있는 worktree
- untracked 잔여물: `git status --short` 의 `??` 파일
- memory-update 리마인드: 남길 교훈이 있으면 `/feedback-review`·`/memory-update`

## 하지 않는 것

- 브랜치 삭제 자동 실행 금지
- 이슈 close 자동 실행 금지
- worktree remove 자동 실행 금지
- main 직접 merge/push 같은 git 조작 자동화 금지
