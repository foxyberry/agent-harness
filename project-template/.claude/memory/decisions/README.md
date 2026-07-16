# decisions/ — 결정 기록 (ADR)

이 폴더는 **"왜 그렇게 결정했나"** 를 한 건씩 남기는 곳이다. 코드는 "무엇을 했나"만 보여준다 —
6개월 뒤 "이거 왜 이렇게 했지"가 사람 머릿속에서 증발하는 걸 막는 게 ADR(Architecture Decision
Record)이다. 회고 루프가 초안을 만들고(`_pending/decisions/`), 사람이 `/memory-update` 로 승격한다.

## 스키마 (frontmatter)

```yaml
---
name: <slug>                 # 기존 메모리 관례 (파일명과 일치)
description: <한 줄 요약>      # INDEX·검색 요약에 쓰인다 — 반드시 채운다
type: decision               # 이 파일이 ADR 임을 표시
id: adr-YYYYMMDD-NNN         # 안정적 링크 대상 (승격 시 확정, 이후 불변)
chain: <chain-slug>          # 축(topic). 같은 chain 끼리만 supersedes 로 연결
status: active               # 저장값은 active | rejected 만. superseded 는 저장하지 않고 조회 시 계산
supersedes: [<id>, ...]      # 이 결정이 대체한 이전 결정 (단방향만!)
keywords: [<검색어>, ...]     # 검색 표면 — 반드시 채운다 (검색 성공이 여기 달림)
commit: <sha>                # 이 결정을 enact 한 커밋(들). 없으면 생략
artifacts:                   # (선택) 산출물 링크 — 본문에 넣지 말고 링크로
  - path: <경로>
---
```

## 본문 필수 섹션 (ADR 게이트)

```markdown
## Context   — 어떤 상황/제약에서 이 결정이 필요했나
## Decision  — 무엇을 하기로 했나 (한두 줄)
## Alternatives — 검토했지만 안 고른 대안 + 왜 버렸나   ← 필수
## Consequence  — 이 결정의 결과/영향 (좋은 것·감수한 것) ← 필수
## Evidence  — 근거: 세션·커밋·PR·이슈 링크
```

> **ADR 게이트:** `Alternatives`(안 고른 대안)나 `Consequence`(결과)가 없으면 그건 ADR 이 아니다.
> 그냥 교훈/규칙이면 `patterns/` 나 일반 메모리로 보내라. 아무 선택이나 ADR 로 만들면 검색이 무너진다.

## 링크 규칙 (단방향)

- `supersedes` 는 **이전 결정 id 를 단방향으로만** 적는다. `superseded_by` 는 **저장하지 않고 조회 시 계산**한다.
  - 이유: 양방향으로 적으면 옛 파일을 계속 수정해야 하고(충돌·반쪽 성공으로 그래프가 깨짐), append-only 가 안전하다.
- 링크는 **id(이름)** 로 문다 — 내용 해시가 아니다. 파일을 정당하게 수정해도 체인이 안 깨지게.
  - (여기서 막으려는 진짜 위험은 "파일 변조"가 아니라 "엉뚱한 결정끼리 잘못 이어붙은 가짜 역사"다.
    그건 해시가 아니라 `chain` 배정 + 사람 승인이 막는다.)

## 자동화에서의 역할 분담

- **자동(회고 LLM)** = 초안 작성자. 초안엔 확정 필드 대신 `proposed_chain` / `proposed_supersedes` /
  `confidence` / `evidence` 만 쓴다.
- **사람(`/memory-update`)** = 계보 관리자. **"기존 체인 계속 / 새 체인(`new:<name>`) / 폐기"** 를
  고르고(모든 ADR 은 정확히 하나의 chain 을 가진다 — 독립 결정이면 새 체인 1개), `id` 확정 +
  `chain`·`keywords` 확인, 대체하면 `supersedes` 에 이전 id. **잘못된 역사는 최악의 실패라 자동 확정 금지.**

## 예시 파일 규약

파일명에 `EXAMPLE` 이 들어간 ADR(예: `adr-EXAMPLE-*.md`)과 이 `README.md` 는 **스키마 견본**이라
`reflect.py` 의 자동화 인덱스에서 제외된다(실제 기존 체인으로 오인돼 supersedes 후보로 주입되는 걸 방지).
네 실제 결정은 `EXAMPLE` 없는 이름으로 만들어라. frontmatter 값은 **한 줄로**(`keywords: [a, b]` 인라인).

## 결정은 작게

한 ADR 에 여러 축을 담으면(예: "전유면적 + 층 정규화 + audit 산출물") 체인이 다시 뒤섞인다.
레코드는 **하나의 결정** 단위로 작게 쪼개고, 산출물은 `artifacts:` 링크로 뺀다.
