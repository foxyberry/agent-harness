---
name: committed-artifact-env-leak
description: 커밋되는 산출물(handoff·메모리)에 환경 정보를 자동으로 넣지 말 것. 기본은 비공개, 라벨이 필요하면 환경변수 opt-in
type: project
---

하네스가 만들어서 **git 에 커밋되는** 산출물에는 실행 환경 정보(호스트명, 절대경로,
사용자명)를 자동으로 채워 넣지 않는다. 기본값은 비공개이고, 라벨이 필요한 팀만
환경변수로 명시적으로 켠다.

**Why:** `handoff.py` 가 `socket.gethostname()` 을 무조건 호출해 실제 장비명을 handoff
헤더에 박았다. 로컬에서만 볼 때는 편의였지만, handoff 는 커밋해서 공유하는 게 존재
이유라 저장소 공개 전환(#71/#72) 시점에 개인 장비명이 그대로 공개될 뻔했다. 편의 기능이
공유 경로를 타고 유출 경로가 된 것 — 공개 직전 감사에서야 잡혔다.

**How to apply:**
- 커밋 대상 산출물을 생성하는 코드에서 `socket.gethostname()`, `os.getcwd()` 절대경로,
  `~` 확장 결과를 헤더·메타데이터에 자동 삽입하지 않는다.
- 필요하면 `HARNESS_HANDOFF_MACHINE` 처럼 **사용자가 직접 준 비민감 라벨만** 기록한다
  (기본값 `비공개`).
- 기본값과 opt-in 을 각각 회귀 테스트로 고정한다 — 기본값이 조용히 되돌아가는 게 위험.
- 새 산출물 포맷을 추가할 때 "이게 커밋되나?" 를 먼저 묻고, 그렇다면 환경 정보 필드를
  넣지 않는다.

관련: [[engine-data-separation]], [[adapter-cross-project-testing]]
