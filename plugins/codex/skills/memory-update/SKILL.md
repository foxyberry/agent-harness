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

`$CLAUDE_PROJECT_DIR/.claude/memory/_pending/` 아래 초안을 **재귀로** 모두 읽는다(하위 디렉토리 포함):
- `_pending/*.md` = 교훈 memory 초안 (type: feedback|project|user|reference)
- `_pending/decisions/*.md` = **의사결정 ADR 초안** (type: decision) → 승격은 아래 **1.6 절** 참조
reflect 잡이 **과거 여러 머지에서 미리 생성**해 둔 초안이다(현재 세션 것만이 아니라 누적분).

- 이 초안들 + 3단계의 현세션 추출 항목을 **하나의 후보 풀로 합쳐 함께 dedup** 한다.
- dedup: (a) 후보끼리 같은 주제면 하나로 병합(예: 거의 동일한 두 초안), (b) 기존 MEMORY.md/메모리 파일과 겹치면 새로 안 만들고 기존 파일 보강.
- 각 후보 판정 = **승격 / 병합 / 폐기**. 사용자에게 간단히 제시하고 확정.
- 처리한 초안은 `_pending/`(및 `_pending/decisions/`) 에서 **삭제**(승격이든 폐기든). 미결정분만 남긴다.

### 1.6 결정(ADR) 초안 승격 — `_pending/decisions/`

`type: decision` 초안은 교훈과 다르게 처리한다(스키마 정본: `.claude/memory/decisions/README.md`).

1. **ADR 게이트 확인**: 본문에 `## Alternatives`(안 고른 대안)와 `## Consequence`(결과)가 **둘 다** 있어야 ADR 이다. 없으면 ADR 로 승격하지 말고 일반 memory 로 돌리거나 폐기.
2. **`proposed_*` 는 제안일 뿐 — 사람이 확정**: 초안의 `proposed_chain`·`proposed_supersedes`·`confidence` 를 사용자에게 제시하고 고르게 한다:
   - **체인(축)**: **"기존 체인 `<slug>` 계속 / 새 체인 `new:<name>` / 폐기"**. **모든 ADR 은 정확히 하나의 `chain` 을 가진다** — 독립 결정이면 새 체인 하나를 판다("체인 없음" 상태는 없다). (잘못된 계보가 최악의 실패 — 자동 확정 금지.)
   - **대체(supersedes)**: 이전 결정을 대체하면 그 `id` 를 `supersedes` 에, 대체 안 하면 `supersedes: []`. (체인 배정과 별개다.)
3. **확정 frontmatter 로 변환** 후 `$CLAUDE_PROJECT_DIR/.claude/memory/decisions/<name>.md` 에 저장:
   - **파일명 = `<name>.md`** (설명적 kebab slug, 초안의 name 유지·정리). `id` 는 **파일명과 별개**의 frontmatter 필드다 — 파일명은 사람이 읽는 이름, `id` 는 링크·supersedes 가 무는 안정적 키.
   - `id: adr-YYYYMMDD-NNN` **부여**(그 날짜의 다음 순번). 한 번 정하면 불변 — 링크 대상이다.
   - frontmatter 값은 **한 줄로** 쓴다(`keywords: [a, b]` 인라인). 인덱스 파서가 줄 단위로 읽는다.
   - `proposed_chain` → `chain`, `proposed_supersedes` → `supersedes`(**단방향만** — `superseded_by` 는 저장하지 말 것, 조회 시 계산), `status: active` 추가, `confidence`·`proposed_*` 제거.
   - `keywords` 는 반드시 채운다(검색 성공이 여기 달림) — 부실하면 보강.
4. **대체 관계 처리(단방향)**: 이 ADR 이 기존 결정을 대체하면, **기존 파일을 수정하지 말고** 새 파일의 `supersedes` 에만 기존 id 를 적는다. 기존 결정의 `status` 는 조회 시점에 "이 id 를 supersedes 하는 게 있으면 superseded" 로 계산(파일 양방향 수정 회피 — 오래된 파일 편집·충돌 방지).
5. **INDEX 등록**: `.claude/memory/INDEX.md` 의 "결정 기록(ADR)" 섹션에 `[<id>](decisions/<name>.md) — [chain: <chain>] <한 줄>` 한 줄 추가.
6. 처리한 초안은 `_pending/decisions/` 에서 삭제. **공유 tier 라 커밋 필요**(브랜치+PR).

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
  > ⚠️ Codex 세션 주의: 위 개인 tier 경로는 **Claude auto-memory** 라 Claude 만 다음 세션에서 자동 로드한다. Codex 는 재로딩 메커니즘이 없으므로, Codex 에서도 필요할 항목이면 공유 tier(커밋 메모리 + INDEX.md)로 저장을 우선 검토하라.
- **공유(프로젝트)** → 둘 중 성격에 맞게:
  - "반드시 매번 지킬 하드 규칙" → **`AGENTS.md`** 해당 섹션에 추가
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
  - `AGENTS.md` 추가분은 해당 섹션에 자연스럽게 편입.

기존 파일 업데이트 시 설명 문구도 같이 갱신.

### 6. 완료 보고

업데이트/추가한 항목을 짧게 요약해서 사용자에게 보고
