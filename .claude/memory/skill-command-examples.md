---
name: skill-command-examples
description: SKILL.md 의 필수 인자는 각주가 아니라 복붙되는 명령 예시 자체에 넣는다
type: feedback
---

스킬 지침에서 어떤 인자가 필수면, 각주("반드시 X 를 넘겨라")로만 안내하지 말고 **fenced 명령
예시 자체에** 그 인자를 넣어라. 에이전트·사용자는 주 예시를 그대로 복붙하지 각주를 반영하지 않는다.

**Why:** 이슈 #3 수정 1차에서 `--project-dir` 를 PATH_NOTE 각주로만 안내했더니, 렌더된 명령
예시엔 인자가 빠져 Codex 리뷰가 "복붙 시 여전히 누락 → 버그 잔존"으로 P2 지적했다.

**How to apply:** build.sh 처럼 어댑터별로 예시가 갈리면 placeholder(예: `{{PROJECT_DIR_ARG}}`)
로 예시 안에 인자를 렌더하고, 필요 없는 어댑터는 빈 값으로 둔다. 각주는 "왜/무엇으로 바꿔라"
설명 보조로만. 관련: [[adapter-cross-project-testing]], [[build-drift]].
