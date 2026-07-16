---
name: adr-EXAMPLE-positive-only-exclusion
description: (예시 ADR — 네 프로젝트 결정으로 교체) fw-both 세션 배제를 positive-only 로
type: decision
id: adr-20260715-001
chain: tool-switch-fw
status: active
supersedes: []
keywords: [fw-both, 세션배제, positive-only, CODEX_THREAD_ID, 자기선택방지]
commit: d6eea9a
---

> 이 파일은 **스키마를 보여주는 예시 ADR** 이다. 네 프로젝트의 실제 결정으로 교체하라.
> (내용은 실제 이 하네스에서 내린 결정이라 형식 참고용으로 진짜다.)

## Context
`fw-both` 는 Claude·Codex 양쪽 세션 로그를 함께 보여주되, **지금 이 명령을 부른 현재 툴의
live 세션**(방금 켠 세션)은 "직전 작업"으로 오인하면 안 된다. 그런데 현재 Codex 가 export 하는
세션 식별 env(`CODEX_THREAD_ID`)가 rollout 의 `session_meta.id` 와 같은지 로그만으로는 확증 불가였다.

## Decision
env 식별자가 **이 프로젝트의 실제 로그와 매칭될 때만** 그 세션을 배제한다(positive-only).
매칭 안 되면 **아무것도 숨기지 않는다.**

## Alternatives
- **"env 미매칭 시 최신 세션을 배제" (fallback)** — 기각. 그 최신이 실은 복원해야 할 직전 작업일 때
  그걸 숨긴다. Codex 리뷰 1라운드가 지적한 버그를 그대로 되살리는 안이라 버렸다.
- **env 값을 그대로 신뢰(대조 없이 배제)** — 기각. env 가 무엇을 가리키는지 확증 못 하는 상태라
  엉뚱한 세션을 배제하거나 아무 효과 없이 지나갈 수 있다.

## Consequence
- (좋음) env 의 정확한 의미를 몰라도 안전하다 — 매칭될 때만 정확히 배제.
- (감수) 최악의 경우 현재 live 세션이 목록에 한 줄 더 보일 수 있다. 하지만 이어받기는 **현재 git 이
  우선**이라 실질 피해가 없다. "직전 작업을 숨김"(나쁨) < "live 한 줄 노출"(경미)의 비대칭을 택한 것.

## Evidence
- 커밋 `d6eea9a`, PR #13 (Closes #6).
- Codex 코드 리뷰 5라운드(env 이름 → 버전 → positive-only → or short-circuit → clean).
- 관련 메모리: verify-other-tool-runtime-ids (다른 툴 식별자 추측 금지).
