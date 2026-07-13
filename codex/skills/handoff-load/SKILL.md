---
name: handoff-load
description: 다른 세션/툴/머신/사람이 남긴 작업을 이어받기. 커밋된 핸드오프를 1순위로 읽고 현재 git 과 대조. 작업 재개 시 사용
context: fork
allowed-tools: Bash, Read, Grep, Glob
argument-hint: "선택: 세션 UUID 또는 transcript 경로 (깊은 복구용)"
---

# 작업 이어받기 (handoff-load)

다른 세션·툴(Codex↔Claude)·머신·사람이 남긴 작업을 이어받는다.
**이식 경로(커밋된 핸드오프)를 1순위**로, 같은 머신이면 transcript 로 보강한다.

## 실행 순서

### 1. 루트 `AGENTS.md` 를 먼저 읽는다 (프로젝트 규칙).

### 2. 핸드오프 + 현재 git 사실 로드

```bash
python3 scripts/handoff.py load --deep
```
> ⚠️ 위 명령의 `scripts/handoff.py` 는 **이 SKILL.md 가 있는 스킬 디렉토리 기준 상대경로**다. 그 스킬 폴더로 cd 해서 실행하되, **반드시 `--project-dir "<지금 작업 중인 사용자 프로젝트의 절대경로>"` 를 함께 넘겨라** — 스킬 폴더는 플러그인 캐시라 사용자 repo 밖일 수 있어, 이 인자 없이는 git 루트 탐지가 빗나가 핸드오프가 엉뚱한 위치에 저장된다.
출력에서 확인할 것:
- **커밋된 핸드오프**: 요약/완료/남은것/다음액션/검증 — 이게 이식 가능한 1순위 정보
- **현재 git 사실**: 핸드오프 작성 이후 바뀐 게 있는지 **대조** (git 이 우선)
- **깊은 복구 힌트**: 같은 머신에 로컬 transcript 가 있으면 표시됨
- **Claude JSONL 빠른 복구**: 최근 Claude Code `.jsonl` 의 마지막 프롬프트/응답/task output 경로를 확인해,
  방금 끊긴 작업이나 백그라운드 리뷰 결과를 이어받음

### 3. (선택) 깊은 복구 — 같은 머신·같은 툴일 때만
`load --deep` 요약만으로 부족하고 로컬 transcript 가 있으면 `~/.codex/sessions` 의 최근 세션 로그
로 .jsonl 을 직접 읽어 더 자세히 복원한다. 특정 파일을 지정해야 하면
`python3 scripts/handoff.py load --deep --transcript <path/to/session.jsonl>` 를 사용한다.
(다른 머신이면 생략 — 파일이 없음)

### 4. "이미 완료 / 남은 것 / 바로 할 액션" 으로 정리한 뒤,
다음 액션이 명확하고 위험하지 않으면 멈추지 말고 진행한다.

## 주의
- transcript·핸드오프보다 **현재 git 상태가 우선**. 이미 커밋/푸시/PR 된 작업 중복 금지.
- 커밋 전 `AGENTS.md` 승인 규칙, main 직접 merge 금지 규칙을 따른다.
