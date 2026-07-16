# 의사결정 소급 마이닝 (Decision mining) — 설계

> 상태: **설계 (탐색)**. 구현 확정 아님. 이슈 [#15](https://github.com/foxyberry/agent-harness/issues/15) 방향 검증용.

## 한 줄

`decisions/`(ADR)가 **앞으로**의 결정을 회고 때 기록(forward-capture)한다면, 이 문서는
**과거** git 히스토리에서 이미 내려진 결정을 **소급 복원**(backward-mine)하는 층을 설계한다.
둘이 합쳐지면: 과거는 마이닝으로 씨앗을 깔고, 이후는 회고로 이어 붙이는 **하나의 결정 계보**.

```
과거 (backward-mine)          현재 이후 (forward-capture)
git log·PR·이슈  ──▶ decisions/  ◀── 회고 루프 (reflect → /memory-update)
     소급 씨앗            ADR 체인              직접 기록
```

## 왜 (동기)

- AI(또는 신규 입사자)는 "지난 N개월 개발 맥락"을 통째로 못 먹는다 — 컨텍스트 한계 = firehose.
- 필요한 건 "더 큰 뷰어"가 아니라 **firehose 를 '왜'의 계보로 압축**하는 층.
- 커밋·PR엔 "무엇"은 풍부해도 "왜"는 드물게 적힌다 → 단순 통계·시각화로는 계보가 안 나온다.

## 시장 포지션 (조사 완료 — #15 결론 요약)

판별 축: **(a)** git 이력에서 rationale("왜")을 뽑아 학습·설명 vs **(b)** 진화 통계·시각화·현재코드 Q&A.

| 부류 | 대표 | 우리와의 차이 |
|------|------|---------------|
| (b) 진화 통계·시각화 | CodeScene, code-maat, git-of-theseus, Hercules | "무엇이 얼마나 바뀌었나"만. "왜" 없음 |
| repo→설명 AI (스냅샷) | DeepWiki, Cody, Continue @codebase, Aider | 현재 코드 기반. 결정 계보 아님 |
| (a) 근접 — 상용 | **Unblocked** (유일하게 "왜"를 코어로 판매) | PR+**Slack+Jira** 융합 — 순수 git 아님 |
| (a) 근접 — 학술 | **CoMRAT** (MSR 2025, 커밋→Decision/Rationale 분류, 오픈툴) | 상용 아님. 커밋 메시지 단독 최충실 |
| (a) 근접 — 신생 | **repowise** ("decision archaeology", ADR 계보 겨냥) | 순수 git 아닌 8소스 병용 |

**핵심 결론 (정직하게):**
- "순수 git 단독으로 결정 계보를 학습·설명"하는 완성 제품은 사실상 없다. 하지만 **빈 gap 도 아니다** —
  2025~2026 여러 팀이 진입 중인 활발한 영역.
- 순수 git 제품이 없는 건 시장 부재가 아니라 **기술적 한계**: git 은 개발자가 커밋에 이유를
  **적었을 때만** rationale 을 담는다. AI 는 안 적힌 WHY 를 발명 못 한다.
- 그래서 실제 차별화는 "순수 git 고집"이 아니라 **git + PR + 세션로그/회고 다중소스 융합**.
  ← 이 지점이 우리 하네스(git 우선 + `fw` 세션로그 + 회고 memory) 설계와 정확히 맞닿는다.

**우리의 방어 가능한 자리**: "git 단독"이 아니라 **"git + 세션로그 + 회고를 한 하네스에서 결정 계보로 융합"**.
Unblocked(Slack/Jira 종속)·CoMRAT(커밋 단독·비상용)·repowise(8소스)와 달리, 우리는
이미 세션로그(`fw`)와 회고(`reflect`)를 한 파이프라인에 갖고 있어 **마이닝 산출물을 같은
`decisions/` 스키마의 씨앗으로 바로 흘려보낼 수 있다.**

## 마이닝 소스 후보 (신호 강도순)

| 소스 | 신호 | 강도 | 한계 |
|------|------|------|------|
| PR 본문·리뷰 토론 | "왜 이 안으로 갔나", 기각된 대안 | **강** | PR 없이 직접 push 한 이력엔 없음 |
| 이슈 본문·코멘트 | 문제 정의, 대안 논의, `Closes #` 링크 | **강** | 이슈 안 쓰는 팀엔 없음 |
| 커밋 메시지 (본문) | rationale, "대신 ~", "되돌림" 마커 | 중 | 한 줄 요약만 쓰면 빈약 |
| 세션로그 (`fw`) | 실제 판단 과정·기각 근거 (우리 고유 자산) | **강** | 같은 머신·로컬 종속 |
| 커밋↔파일 churn | "어디가 자주 바뀌나" = 결정 압력 지점 | 약 | "왜"는 아님. 후보 지목용 |
| revert·`supersedes` 흔적 | 방향 전환 = ADR 후보 | 중 | 탐지 규칙 필요 |

핵심: **PR·이슈·세션로그가 "왜"의 주 광맥**이고, 커밋 churn 은 "어디를 파볼지" 지목하는 보조.

## 하네스 접점 (설계)

마이닝 산출물은 **새 스키마를 만들지 않고** 기존 `decisions/` ADR 스키마의 **초안**으로 떨군다 —
즉 forward-capture 와 **같은 승격 경로**(`_pending/decisions/` → `/memory-update` 1.6)를 탄다.

```
git log --grep + PR/이슈 API  ──▶  마이닝 LLM  ──▶  _pending/decisions/*.md
                                    (rationale 추출)     (proposed_chain/supersedes/confidence)
                                                              │
                                                     사람이 /memory-update 로 승격
                                                     (엉뚱한 계보 = 최악 실패 → 자동 확정 금지)
```

- **재사용**: `reflect.py` 의 초안 emit 계약(`proposed_*`·게이트)·`_decisions_index`(기존 체인 주입)·
  1.6 승격 절차를 그대로 재사용. 마이닝은 "트랜스크립트" 대신 "git 히스토리 슬라이스"를 입력으로 주는
  **또 다른 초안 생성기**일 뿐이다.
- **엔진↔데이터 원칙 준수**: 마이닝 규칙(어떤 커밋 패턴이 결정 신호인가)은 core 하드코딩 X →
  프로젝트 데이터(예: `decision-mining-rules.json`)로 뺀다. `reflection-rules.json` 선례를 따른다.
- **`fw` 와의 관계**: `fw` 는 세션로그를 **이어받기**용으로 읽는다. 마이닝은 같은 로그를 **결정 추출**용으로
  읽는다 — 리더는 공유 가능, 소비 목적만 다르다.

## 한계 직시 (설계에 못 박을 것)

1. **커밋에 "왜"가 없으면 마이닝도 못 뽑는다.** AI 는 안 적힌 rationale 을 발명하면 안 된다 —
   그건 가짜 역사다. 신호 없는 커밋은 **조용히 건너뛴다**(빈 초안 강제 생성 금지).
2. **엉뚱한 계보가 최악의 실패.** 마이닝이 chain·supersedes 를 **확정하면 안 된다** — forward-capture 와
   똑같이 `proposed_*` 로만 제안하고 사람이 승격. 자동 확정 절대 금지.
3. **우리 강점과 상호보완**: 마이닝(과거·불완전) × 회고 forward-capture(현재 이후·"왜"를 즉시 기록)는
   경쟁이 아니라 보완. 과거의 빈 곳은 마이닝이 씨앗만 깔고, 앞으로는 회고가 채운다.
4. **positive-only 정신 계승**: 확신 없는 결정 신호는 **주입 안 함**(억지 ADR 생성 X).
   [[verify-other-tool-runtime-ids]] 의 "매칭될 때만 작동" 설계와 같은 결.

## 다음 (구현 승격 시)

- [ ] PoC: `git log --grep` + PR/이슈 본문 → 마이닝 LLM → `_pending/decisions/` 초안 (이 repo 히스토리로 dogfood)
- [ ] `decision-mining-rules.json` 데이터 스키마 (결정 신호 패턴)
- [ ] `reflect.py` 초안 생성기와의 코드 공유 지점 확정 (입력만 다른 같은 파이프라인)
- [ ] 벤치마크: 이 repo 의 실제 PR(#6·#13·#16)에서 소급 ADR 이 나오는지 정성 평가

## 관련

- 이슈 #15 (이 설계의 근거·시장조사 전문), #14(forward-capture, PR #16 으로 머지됨)
- `docs/self-improvement-hooks.md` (회고 루프 — 마이닝이 접속할 승격 경로)
- `core/hooks/reflect.py` (재사용할 초안 생성기), `.claude/memory/decisions/README.md` (ADR 스키마 정본)
