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
python3 scripts/handoff.py load
```

출력에서 확인할 것:
- **커밋된 핸드오프**: 요약/완료/남은것/다음액션/검증 — 이게 이식 가능한 1순위 정보
- **현재 git 사실**: 핸드오프 작성 이후 바뀐 게 있는지 **대조** (git 이 우선)
- **깊은 복구 힌트**: 같은 머신에 로컬 transcript 가 있으면 표시됨

### 3. (선택) 깊은 복구 — 같은 머신·같은 툴일 때만
핸드오프만으로 부족하고 로컬 transcript 가 있으면 `~/.codex/sessions` 의 최근 세션 로그
로 .jsonl 을 직접 읽어 더 자세히 복원한다. (다른 머신이면 생략 — 파일이 없음)

### 4. "이미 완료 / 남은 것 / 바로 할 액션" 으로 정리한 뒤,
다음 액션이 명확하고 위험하지 않으면 멈추지 말고 진행한다.

## 주의
- transcript·핸드오프보다 **현재 git 상태가 우선**. 이미 커밋/푸시/PR 된 작업 중복 금지.
- 커밋 전 `AGENTS.md` 승인 규칙, main 직접 merge 금지 규칙을 따른다.
