# stale issue/PR detector — 설계 (MVP)

> 에픽 [#26](https://github.com/foxyberry/agent-harness/issues/26) P1. `/plan-feature` 산출.
> ① 방향은 Codex 방향 리뷰 1R 을 반영해 **고정밀 MVP** 로 좁힘.

## 배경 / 문제

오래된 GitHub 이슈가 **이미 해결됐는지** 사람이 매번 수동으로 확인해야 한다. 방금 tutti-dpnc #1441·#1413·#1391 을 손으로 판정한 게 그 수동 버전이다. 시간이 들고, 빼먹으면 stale 이슈가 쌓인다.

## 접근 (합의된 방향)

**자동 close 하지 않는 advisory 리포트.** GitHub 가 **명시적으로 연결한 "닫는 merged PR"** 만 1차 신호로 쓴다. 근거가 없으면 "불확실/유지"로 두고 **닫지 않는다.** 고정밀(precision) 우선.

**판정 규칙 (결정론):**
- 이 이슈를 닫는 **merged PR 이 GitHub 연결 데이터에 존재** → **닫기 후보** (고정밀).
  - 출처: PR 의 `closingIssuesReferences`, issue timeline 의 cross-reference/connected 이벤트, PR body 의 `Fixes/Closes #`. (`gh api graphql`)
- 그런 연결이 없음 → **불확실 / 유지 검토** (닫지 않음).
- **정책 라벨 제외:** `keep·blocked·needs-repro·tracking·epic·good first issue` 등은 후보에서 빼거나 별도 표시. 메타/트래킹 이슈는 merged PR 이 여러 개여도 닫지 않는다.

**운영 위치:** **명시 실행 command/skill** (또는 scheduled report). **SessionStart 훅 금지** — gh 비용·rate limit·지연·private repo auth 실패가 사용자 흐름을 방해한다.

**출력:** 이슈별 `닫기후보 / 불확실 / 유지` + **근거 링크**(연결 PR·커밋). 사람이 보고 판단.

## 안 고른 대안 (Codex 방향 리뷰 산물)

- **자동 close** — 기각. 오탐 한 번이면 신뢰가 죽는다. advisory 로만.
- **issue body 의 `Closes/Fixes #` 를 1차 신호로** — 기각/격하. close 키워드는 issue 가 아니라 PR·커밋·timeline 에 산다. GitHub 연결 데이터가 정본.
- **`rg` 코드 흔적으로 판정** — v2 로 격하. 구현 흔적이 있어도 전체 해결·회귀테스트·남은 경로는 모른다. MVP 에선 "불확실 이슈 재검토 보조"로만.
- **이슈 나이·활동을 close 점수에** — 격하. 그건 **정렬** 신호지 close 신호가 아니다. 오래됐어도 유효할 수 있다(stale ≠ resolved). MVP 에선 정렬에만 사용.
- **LLM 의미 매칭** — v2. 1차는 결정론 우선, LLM 은 선택적 재정렬만.

## 스코프

**MVP (한다):** 연결된 merged PR 기반 고정밀 판정 · 정책 라벨 제외 · advisory 리포트 command · 근거 링크 · 나이는 정렬에만.

**v2 (안 한다):** `rg` 코드 흔적 보조 · LLM 의미 매칭·재정렬 · 자동 close · scheduled 자동 실행.

## 작업 분해 + 의존

```
[A] 수집 + 정책 필터 ─┐
                      ├─▶ [C] 판정 + advisory 리포트 command
[B] 연결 PR 리졸버 ──┘
```
- **A**(수집·정책필터)와 **B**(연결 PR 리졸버)는 **의존 없음 → 병렬**.
- **C**(판정+리포트)는 A·B 산출을 합침 → **선행 A, B**.

## 리스크 / 열린 질문

- **오탐** — 고정밀 지향(연결 PR 있을 때만 후보) + advisory + 근거 필수.
- **메타/트래킹 이슈** — 정책 라벨로 제외. 어떤 라벨을 제외 목록에 넣을지는 repo 별 config 화 고려.
- **gh rate limit** — 배치 조회(`gh api graphql` 한 번에), 우리 `gh-rate-limit` 훅과 상호작용. 대량 조회는 paginate.
- **private repo auth** — 실행 시 실패 가능 → command 라 사용자 흐름 밖에서 처리.
- **대상 범위** — 자기 repo 만? 여러 repo? MVP 는 현재 repo, 인자로 확장 고려.
