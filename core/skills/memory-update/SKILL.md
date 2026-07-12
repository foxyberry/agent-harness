---
name: memory-update
description: 이 세션에서 배운 것과 reflect 잡이 만든 대기 초안(_pending)을 검토·승격해 메모리에 영속화. 머지 후·회고 시 사용
context: full
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
argument-hint: "(선택) 특정 항목만 정리하려면 입력"
---

# 메모리 업데이트 (memory-update)

이 세션에서 배운 것과, reflect 잡이 과거 머지에서 미리 만들어 둔 대기 초안(`_pending`)을
함께 검토해 memory 로 영속화한다.

## Memory 업데이트 프로세스

### 1. 현재 MEMORY.md 읽기
auto-memory 디렉토리의 `MEMORY.md` 를 읽는다.
경로 = `~/.claude/projects/<프로젝트 절대경로에서 '/' → '-' 치환>/memory/MEMORY.md`
(시스템 메모리 지침에 현재 머신·프로젝트의 정확한 경로가 주어지면 그걸 사용)

### 1.5 대기 초안(_pending) 수집 — reflect 잡이 미리 만든 초안

`$CLAUDE_PROJECT_DIR/.claude/memory/_pending/*.md` (프로젝트 루트 기준 `.claude/memory/_pending/`) 를 모두 읽는다.
reflect 잡이 **과거 여러 머지에서 미리 생성**해 둔 초안이다(현재 세션 것만이 아니라 누적분).

- 이 초안들 + 3단계의 현세션 추출 항목을 **하나의 후보 풀로 합쳐 함께 dedup** 한다.
- dedup: (a) 후보끼리 같은 주제면 하나로 병합(예: 거의 동일한 두 초안), (b) 기존 MEMORY.md/메모리 파일과 겹치면 새로 안 만들고 기존 파일 보강.
- 각 후보 판정 = **승격 / 병합 / 폐기**. 사용자에게 간단히 제시하고 확정.
- 처리한 초안은 `_pending/` 에서 **삭제**(승격이든 폐기든). 미결정분만 남긴다.

⚠️ v1 한계: 폐기한 초안은 메모리에 안 남아 이후 세션 트랜스크립트에서 **재생성될 수 있다**(재등장 시 다시 폐기). 생성-시 dedup은 name 중복만 막는다.

### 2. 후보 = (대기 초안) + (이 세션 추출). 아래 항목을 추출

**feedback (실수 지적 / 확인된 좋은 패턴)**
- 사용자가 "왜그래", "하지마", "틀렸어", "실수" 등으로 지적한 것
- 반복하면 안 될 행동
- 사용자가 "맞아", "좋아", "그렇게 해줘" 등으로 확인한 비자명한 패턴

**project (프로젝트 현황 변경)**
- 새로 머지된 PR, 추가된 기능
- 중요 설계 결정 변경
- 새로 등록된 이슈 중 중요한 것
- API 구조 변경

**reference (새로 알게 된 외부 리소스)**
- 새 문서, 대시보드, 채널 등

### 2.5 scope 분류 (개인 vs 프로젝트) + 라우팅 — 어디에 저장할지

각 후보를 **type과 별개로 scope로 분류**해 저장 위치를 정한다:

| type | scope | 저장 tier |
|------|-------|-----------|
| user | 개인 | 개인 |
| reference / project | 프로젝트 | 공유 |
| **feedback** | **케이스별 판단** | 아래 |

**feedback scope 판단:**
- **개인 취향** (말투·선호·이 유저와 일하는 방식: "결론부터 짧게", "이 방식 싫어") → 개인
- **프로젝트 규칙** (코드베이스/팀이 지켜야 할 것: "main 직접 푸시 금지", "kotlin javaParameters 필수", "Spring DI 패턴") → 공유
- **애매하면** (개인 습관인지 팀 관행인지 불분명) → **사용자에게 질문**: "이거 개인 취향이에요, 프로젝트 규칙이에요?" → 개인 / 프로젝트 / 안함

**저장 위치 (scope별):**
- **개인** → `~/.claude/projects/<프로젝트 인코딩>/memory/<name>.md` + 그곳 `MEMORY.md` 인덱스 (per-machine, 커밋 무관 — step 1 의 읽기 경로와 동일해야 이후 세션에서 로드됨)
{{PERSONAL_TIER_NOTE}}
- **공유(프로젝트)** → 둘 중 성격에 맞게:
  - "반드시 매번 지킬 하드 규칙" → **`{{RULES_FILE}}`** 해당 섹션에 추가
  - "참고 사실·패턴·설계 결정" → repo **`$CLAUDE_PROJECT_DIR/.claude/memory/<name>.md`** (frontmatter; [[memory-search]] 훅이 Edit/Write 시 노출)

⚠️ 공유 tier 저장분은 **커밋 필요**(브랜치+PR — main 직접 금지). 개인 tier는 ~/.claude라 커밋 무관. 완료 보고에 "공유분 = commit/PR 필요" 표시.

### 3. 저장 규칙

**중복 확인 필수**: 기존 파일이 있으면 새 파일 만들지 말고 기존 파일 업데이트

**저장할 것 vs 저장 안 할 것**
- ✅ 반복될 실수, 비자명한 패턴, 설계 결정의 Why
- ✅ API 구조/지표 목록처럼 다음 세션에서 참고할 현황
- ❌ 일시적인 작업 내용 (이번에만 쓰는 것)
- ❌ 코드에서 읽으면 알 수 있는 것
- ❌ git log/blame으로 알 수 있는 것

### 4. 파일 작성 형식

```markdown
---
name: 메모리 이름
description: 한 줄 설명 — MEMORY.md 인덱스에 표시됨
type: feedback | project | reference | user
---

내용 (feedback/project는 **Why:** 와 **How to apply:** 포함)
```

### 5. 인덱스 업데이트 (tier별)

- **개인 tier**: `~/.claude/.../memory/MEMORY.md` 에 한 줄 추가/갱신:
  ```
  - [이름](./파일명.md) — 한 줄 설명
  ```
- **공유 tier**:
  - `.claude/memory/<name>.md` 추가 시 **`.claude/memory/INDEX.md` 에 한 줄 등록** — Claude 는 [[memory-search]] 훅으로, Codex 는 이 인덱스로 읽는다.
  - `{{RULES_FILE}}` 추가분은 해당 섹션에 자연스럽게 편입.

기존 파일 업데이트 시 설명 문구도 같이 갱신.

### 6. 완료 보고

업데이트/추가한 항목을 짧게 요약해서 사용자에게 보고
