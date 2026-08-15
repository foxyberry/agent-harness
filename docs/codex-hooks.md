# Codex 훅 — 공식 문서 정리 + 실측 보완

**1차 출처는 공식 문서다.** 이 문서는 그 요약이고, 우리가 직접 확인한 것만 "실측" 으로 구분해
덧붙인다.

- 공식: <https://learn.chatgpt.com/docs/config-file/config-advanced>
- 확인 시점: 2026-08-10 / codex-cli 0.145.0

> **정정 이력:** 이 문서의 앞선 두 판은 바이너리 문자열과 rollout 로그 역추론으로 썼고,
> **도구 이름을 틀렸다**(`exec` 라고 단정 → 실제 canonical 은 `Bash`·`apply_patch`).
> 로그의 `exec` 는 code mode 내부 이름이라 훅 계층과 레이어가 다르다. 문서를 먼저 봤으면
> 안 틀렸다. 역추론은 문서가 없을 때의 보조 수단이다.

## 결론

Codex 훅은 Claude 와 **형식이 거의 같다.** 훅 스크립트 본문은 대부분 손대지 않고 양쪽에서
돌릴 수 있다. 다만 **커버리지 한계**와 **신뢰 절차**가 다르다.

## 이벤트

**턴 단위:** `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`,
`UserPromptSubmit`, `SubagentStop`, `Stop`

**세션 단위:** `SessionStart`, `SubagentStart`, `SessionEnd`(⚠️ 아래 참조 — 발화 미검증)

Claude 대비 `PermissionRequest`·`PreCompact`/`PostCompact`·`Stop`/`SubagentStop`·`SubagentStart`
가 더 있다.

> **`SessionEnd` — 목록에는 있으나 발화는 미검증.** 위 공식 문서 페이지의 이벤트 목록에는
> `SessionEnd` 가 없다. 그런데 **Codex 의 `/hooks` 화면이 이 이벤트를 목록에 표시한다**
> (`Right before a session ends`, 0.145.0). 바이너리 문자열에도 있다.
>
> 다만 **실제로 발화하는 것을 관측하지는 못했다.** `/hooks` 에 보이는 것은 "설정 가능한
> 이벤트"라는 뜻이지 "우리 환경에서 반드시 dispatch 된다"는 증명이 아니다.
> **정리 작업(cleanup) 훅을 여기에 걸기 전에 반드시 실제 발화를 한 번 관측하라** — 안 뜨면
> 무음으로 안 도는데, 세션 종료 훅은 안 돌아도 티가 안 난다.
>
> 이 구분을 일반화하면: **열거형 항목**(이벤트 목록)은 문서가 불완전할 수 있어 실물 교차
> 확인이 값싸지만, 그 결과는 "존재"까지만 말해준다. **계약**(도구 이름, 입출력 스키마)은
> 실물 역추론이 특히 위험하다 — 이 문서의 앞선 판이 `tool_use_id` 접두사 `exec-` 를 도구
> 이름으로 오인한 게 그 예다. 그리고 **"동작한다"는 발화 관측으로만 증명된다.**

## 도구 이름 (matcher 대상)

`matcher` 는 **도구 이름에 대한 정규식**이다. 생략하거나 `"*"`·`""` 이면 모든 발생에 매칭.

| 이름 | 대상 |
|---|---|
| `Bash` | 셸 명령 |
| `apply_patch` | 파일 편집 — matcher 는 `Edit`·`Write` 도 받는다 |
| `mcp__<server>__<tool>` | MCP 도구 |

⚠️ **rollout 로그에 보이는 `exec` 는 훅의 도구 이름이 아니다.** 실측으로 정체가 밝혀졌다 —
훅 입력의 **`tool_use_id` 접두사**다(`exec-9fa03e9a-13d8-...`). `tool_name` 은 그와 별개로
`Bash`·`apply_patch` 가 온다. 로그로 matcher 값을 정하지 말 것.

실제 입력 예시(발췌):

```json
{"hook_event_name":"PreToolUse","tool_name":"Bash",
 "tool_input":{"command":"echo hello"},
 "tool_use_id":"exec-c22ab2e4-ba2c-44ac-81c1-7f8d99969ef7"}

{"hook_event_name":"PreToolUse","tool_name":"apply_patch",
 "tool_input":{"command":"*** Begin Patch\n*** Add File: /tmp/x/test.txt\n+world\n*** End Patch"},
 "tool_use_id":"exec-9fa03e9a-13d8-438e-bb96-796a2717a0fe"}
```

**`apply_patch` 의 `tool_input.command` 는 패치 원문 그대로다** — JS 래퍼가 아니다.
`*** Begin Patch` / `*** Add File:` / `*** Update File:` / `*** Move to:` / `+` 라인을 그대로
파싱하면 된다. `PostToolUse` 에는 `tool_response` 가 추가로 온다.

## ⚠️ 커버리지 한계 — 이게 가장 중요하다

> `PreToolUse` and `PostToolUse` intercept **"simple" shell calls only**, not the newer
> `unified_exec` mechanism or tools like `WebSearch`. — *"doesn't intercept all shell calls yet"*

**실측 (2026-08-10, 실제 사용자 환경 / code mode 기본값):** `PreToolUse`·`PostToolUse` 둘 다
**정상 발화했다.** 셸 실행과 `apply_patch` 편집 모두 잡혔고, matcher 도 정확히 매칭됐다.

| 동작 | `tool_name` | 매칭된 matcher |
|---|---|---|
| `echo hello` | `Bash` | matcher 없음, `Bash` |
| 파일 생성 | `apply_patch` | matcher 없음, `apply_patch` |

따라서 이 한계가 **평범한 셸·편집 호출에는 해당하지 않는다.** 다만 문서가 `unified_exec` 를
명시적으로 제외하므로, 그 경로를 쓰는 환경에서는 여전히 안 걸릴 수 있다. 이식 시에는
대상 환경에서 한 번 관측하는 게 안전하다 — **안 뜨는 걸 matcher 이름 문제로 오진하기 쉽다.**

## 입력 (stdin JSON)

**공통:** `session_id`, `transcript_path`(nullable), `cwd`, `hook_event_name`, `model`,
`permission_mode`(`default`|`acceptEdits`|`plan`|`dontAsk`|`bypassPermissions`)

**턴 단위 추가:** `turn_id`

**이벤트별:**

| 이벤트 | 추가 필드 |
|---|---|
| `PreToolUse`/`PostToolUse` | `tool_name`, `tool_use_id`, `tool_input` (Bash·apply_patch 는 `command` 를 가진 객체) |
| `PermissionRequest` | `tool_name`, `tool_input`(선택적 `description`) |
| `SessionStart`/`SubagentStart` | `source` / `agent_type`, `agent_id` |
| `PreCompact`/`PostCompact` | `trigger` (`manual`\|`auto`) |
| `Stop`/`SubagentStop` | `stop_hook_active`, `last_assistant_message` |

## 출력 (stdout)

공통: `continue`, `stopReason`, `systemMessage`, `suppressOutput`

| 이벤트 | 고유 출력 |
|---|---|
| `PreToolUse` | `permissionDecision`(`allow`\|`deny`) + `permissionDecisionReason`, `additionalContext`, `updatedInput` |
| `PostToolUse` | `decision: "block"` + `reason`, `additionalContext` |
| `UserPromptSubmit` | `decision: "block"` + `reason`; `additionalContext` 는 developer context 로 |
| `SessionStart`/`SubagentStart` | 평문 stdout 이 developer context 가 된다. `hookSpecificOutput.additionalContext` JSON 도 동작 |

평문 stdout 은 대부분의 이벤트에서 무시되고, `SessionStart`·`SubagentStart`·`UserPromptSubmit`
에서만 컨텍스트로 들어간다.

## exit code

| 코드 | 의미 |
|---|---|
| `0` + JSON | 성공, 출력 파싱 |
| `0` + 출력 없음 | 성공, 그대로 진행 |
| **`2`** | **차단/거부** — 사유는 stderr 에 |
| 그 외 non-zero | 훅 실패로 보고 |

## 설정 위치 (우선순위 순)

1. `~/.codex/hooks.json` 또는 `~/.codex/config.toml` 의 `[hooks]` (user)
2. `<repo>/.codex/hooks.json` 또는 `<repo>/.codex/config.toml` 의 `[hooks]` (project)
3. 플러그인 번들 `hooks/hooks.json` 또는 매니페스트가 지정한 경로

한 레이어에 `hooks.json` 과 인라인 `[hooks]` 가 둘 다 있으면 병합하고 경고한다.

플러그인은 매니페스트에 `"hooks": "./hooks/hooks.json"` 로 등록한다(실측).

TOML 인라인 형태:

```toml
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/policy.py"'
timeout = 30
statusMessage = "Checking Bash command"
```

`$(git rev-parse --show-toplevel)` 는 **문서가 쓰는 관용구**다.

## 신뢰(trust) — 안 하면 무음으로 건너뛴다

- **프로젝트 훅**(`<repo>/.codex/`): `.codex/` 레이어가 신뢰돼야 로드된다. 명시적 검토·신뢰 필요.
  신뢰는 **훅 해시 기준**으로 기록되므로 **내용이 바뀌면 재검토**가 뜬다.
- **user/system 훅**: 프로젝트가 미신뢰여도 자기 레이어에서 로드된다. 검토·신뢰 절차는 동일.
- **managed 훅**(`requirements.toml`·MDM·정책): 정책상 신뢰 처리, 사용자가 못 끈다.
- **우회**: `--dangerously-bypass-hook-trust` (검증된 훅에만).

⚠️ 미신뢰 훅은 **에러도 경고도 없이** 건너뛴다. 설치 성공처럼 보이므로 사용자 안내에 반드시
포함해야 한다.

## 환경 변수

**플러그인 훅:** `PLUGIN_ROOT`, `PLUGIN_DATA` (Codex 고유) + `CLAUDE_PLUGIN_ROOT`,
`CLAUDE_PLUGIN_DATA` (**호환 별칭**)

**모든 훅:** 세션 `cwd` 가 작업 디렉터리로 설정된다.

⚠️ **`CLAUDE_PROJECT_DIR` 은 주어지지 않는다**(실측). 프로젝트 경로는 입력 JSON 의 `cwd` 로
얻는다. 프로세스 cwd 가 플러그인 루트가 아니므로 **상대경로 `command` 는 실패**한다(실측) —
`${CLAUDE_PLUGIN_ROOT}` 기준 절대경로나 문서의 `$(git rev-parse ...)` 관용구를 쓴다.

```python
def _project_dir(data=None):
    return (os.environ.get("CLAUDE_PROJECT_DIR")     # Claude
            or (data or {}).get("cwd")               # Codex
            or os.getcwd())
```

## 기타 제약

- `type: "command"` 만 실행된다. `prompt`·`agent` 타입은 파싱만 하고 건너뛴다.
- async command 훅은 파싱되나 실행되지 않는다.
- 기본 타임아웃 600초, `timeout`(초)로 조정.
- 같은 이벤트에 매칭된 훅 여러 개는 **동시 실행**되며 서로를 막을 수 없다.
- `PreToolUse` 는 완전한 강제가 아니다 — 다른 도구로 우회 가능.

## 주입 검증법 (재현용)

훅이 실제로 컨텍스트를 주입했는지는 **모델이 파일을 직접 읽어서 답한 것과 구별해야** 한다.
canary 문자열을 `.claude/memory/INDEX.md` 에만 두고 훅 켬/끔 두 번 돌린다.

```bash
export CODEX_HOME=<격리 경로>            # 실제 ~/.codex 오염 방지
codex plugin marketplace add <repo>
codex plugin add agent-harness@foxyberry

P="세션 시작 시 주어진 컨텍스트에 canary 가 있으면 그것만 출력. 파일 읽지 마. 없으면 NONE."
codex exec "$P"                                    # 대조군(훅 무시) → NONE
codex exec --dangerously-bypass-hook-trust "$P"    # 실험군(훅 실행) → CANARY
```

실측 결과가 `NONE` / `SPIKE_CANARY_12345` 로 갈렸다. **"파일을 읽지 마"를 넣지 않으면 모델이
그냥 읽어버려서 실험이 무의미해진다.**

⚠️ **격리 `CODEX_HOME` 에 `auth.json` 을 복사하지 마라.** refresh token 은 1회용이라 원본과
경쟁해 양쪽 다 깨질 수 있다. 격리 홈에서는 `codex login` 을 따로 한다.

검증은 harness repo **밖** 별도 프로젝트에서 한다([[adapter-cross-project-testing]]).

## 무음 실패 잡기 (이슈 #85 4단계)

훅이 안 돌아도 화면에는 아무 일도 안 일어난다. "안 돌았다"와 "돌았는데 할 말이 없었다"가
바깥에서 똑같이 생겼기 때문이다. 그래서 두 겹으로 나눠 본다.

### 1. 저장소 안 — 배선 테스트

`tests/test_hook_wiring.py` 가 `plugins/*/hooks/hooks.json` 을 읽어 확인한다.

| 실패 모드 | 어떻게 잡나 |
|---|---|
| hooks.json 경로 오타 | 등록된 스크립트가 그 번들에 실제로 있나 |
| helper cp 누락(`hook_io`·`repo_identity`) | 등록된 훅을 **번들 디렉토리에서** 실행해 exit 0 확인 |
| matcher 불일치 | matcher 가 실측 도구 이름(`Edit`/`Write`/`MultiEdit`/`Bash`, `apply_patch`/`Bash`)을 덮나 |
| 정규화는 되는데 훅이 안 뜸 | 편집 픽스처의 `tool_name` 을 편집 훅 matcher 가 받나 |

도구 이름 목록은 matcher 에서 뽑지 않는다 — 그러면 자기가 자기를 검사하는 순환이라 아무것도
못 잡는다. 출처는 이 문서의 실측표다.

이 테스트는 생성물(`plugins/*/hooks/hooks.json`)을 읽으므로 `./build.sh` 를 안 돌리면 실패한다.
그건 고장이 아니라 빌드 드리프트 감지다.

### 왜 자체 계기가 필요한가 — 툴 로그로는 안 된다

"훅이 돌았나"를 툴이 남기는 로그로 알 수 없나? 실측으로 확인했다(2026-08-15, `tutti-dpnc`).

**Codex rollout 로그**: 훅 실행 기록이 **아예 없다.** 훅이 주입한 텍스트는 대화의 일부로
들어가지만, 어떤 훅이 넣었는지도 훅이 돌았다는 사실도 안 남는다.

**Claude 세션 `.jsonl`**: 남긴다. `type: attachment` 항목에 `hookEvent` 와 훅 stdout 원문이
통째로 들어간다. 그런데 **일부만** 남는다 — 같은 세션의 trace 와 대조한 결과:

| 이벤트 | 실제 발화(trace) | Claude 로그 |
|---|---|---|
| SessionStart | 2 | 3 |
| UserPromptSubmit | 3 | 0 |
| PreToolUse | 3 | 0 |
| PostToolUse | 3 | 1 |

빠진 것들의 공통점은 **주입할 게 없어서 조용히 끝난 실행**이다. `memory-search` 는 세 번 다
떴지만 걸리는 라우트가 없어 아무것도 안 냈고, 그래서 안 남았다. 정황상 **출력을 낸 실행만
기록**하는 것으로 보인다(규칙 자체를 확인하진 않았다. 다만 이벤트 종류로 거르는 건 아니다 —
PostToolUse 는 기록되는 이벤트인데도 3번 중 1번만 남았다).

**결론:**

| 알고 싶은 것 | Codex 로그 | Claude 로그 | `HARNESS_HOOK_TRACE` |
|---|---|---|---|
| 돌았고 뭔가 주입했다 | 역추론 가능 | ✅ | ✅ |
| 돌았지만 조용했다 | ❌ | ❌ | ✅ |
| 아예 안 돌았다 | ❌ | ❌ | ✅ |

양쪽 로그 다 **"조용히 돈 것"과 "안 돈 것"을 구별해 주지 못한다.** 그게 정확히 우리가 3주간
못 알아챈 실패 모드다. Claude 로그는 부분적 대체재는 되지만 **부재를 증명하지는 못한다.**

### 2. 저장소 밖 — 진입 추적 (`HARNESS_HOOK_TRACE`)

설치본이 미신뢰라 skip 되는 것, 실제 툴이 훅을 정말 띄우는지는 **설치 상태·런타임**이라
이 저장소의 테스트가 볼 수 없다. 대상 프로젝트에서 관측한다.

`HARNESS_HOOK_TRACE` 에 경로를 주면 등록된 훅이 **진입 시점에** 한 줄씩 JSONL 로 남긴다.
`emit_context` 가 아니라 진입에 남기는 게 핵심이다 — 주입 시점에 남기면 "돌았는데 라우트에
안 걸린" 경우와 "아예 안 돈" 경우가 또 같아져서 아무것도 못 가린다. 환경변수가 없으면
아무 일도 안 한다(평소 비용 0).

```bash
export HARNESS_HOOK_TRACE=/tmp/hook-trace.jsonl
rm -f "$HARNESS_HOOK_TRACE"
codex          # 또는 claude — harness repo 밖 별도 프로젝트에서
# 세션 안에서: 셸 명령 하나(`echo hi`) + 파일 편집 하나
cat /tmp/hook-trace.jsonl
```

기대 결과 — 등록된 (이벤트, 훅) 조합마다 최소 한 줄:

| 툴 | 있어야 할 줄 |
|---|---|
| Codex | `project-memory-index`(SessionStart), `memory-search`(PreToolUse ×2), `reflection`(PostToolUse) |
| Claude | 위 셋 + `pr-merge-reflect`(SessionStart·UserPromptSubmit·PostToolUse) |

줄이 **없는** 훅이 무음 실패다. 원인은 셋 중 하나다 — 플러그인 미신뢰(→ [신뢰](#신뢰trust--안-하면-무음으로-건너뛴다)),
matcher 불일치(→ 위 배선 테스트), 설치본이 구버전(→ 설치 경로·버전 확인).

### 관측 결과 (2026-08-15, `tutti-dpnc` — harness repo 밖)

플러그인 0.7.1. **양쪽 어댑터의 등록된 훅이 전부 실제로 떴다.**

| 훅 | Claude | Codex |
|---|---|---|
| `project-memory-index` (SessionStart) | ✅ | ✅ |
| `memory-search` (PreToolUse — 셸·편집 둘 다) | ✅ | ✅ |
| `reflection` (PostToolUse — 편집) | ✅ | ✅ |
| `pr-merge-reflect` (SessionStart·UserPromptSubmit·PostToolUse) | ✅ | — 미이식이라 안 뜨는 게 정상 |

`HARNESS_HOOK_TRACE` 는 **양쪽 다 훅 서브프로세스까지 전파된다**(Codex 도 별도 설정 불필요).

**대조군이 같이 잡혔다** — 이게 있어야 "전부 뜬다"가 증거가 된다.

- Claude: Write 를 쓴 라운드에서 `pr-merge-reflect` PostToolUse 가 **안 떴다**(matcher 가 `Bash`).
  Bash 라운드에서만 떴다.
- Codex: 셸 호출에서 `reflection` 이 **안 떴다**(matcher 가 `apply_patch`). 편집에서만 떴다.

추적 줄이 나온다는 것 자체가 **설치본 버전의 증거**이기도 하다 — 0.7.0 이하에는 `trace_entry`
가 없어서 아예 못 찍는다.

### 관측하면서 밟은 함정 두 개

1. **계기를 넣은 PR(#101)이 버전을 안 올려서, 그게 깔린 설치본이 한 군데도 없었다.**
   그대로 관측했으면 0줄이 나오고 "훅이 안 뜬다"로 오독했을 것이다. #101 이 잡으려던 함정을
   #101 이 밟았다. → 관측 전에 **설치 캐시에 `trace_entry` 가 있는지부터 grep 한다.**
2. **첫 시도는 시험이 성립을 안 했다.** "파일 만들어줘"라고 하니 세션이 셸로 만들어
   편집 도구를 한 번도 안 썼고, `reflection` 이 안 떴다. 세션 로그에 `tool=Bash` 두 번뿐인 걸
   확인하고서야 알았다. **훅 문제가 아니라 시험 설계 문제였다** — 무음 실패를 조사할 때
   이 오진이 제일 쉽게 난다. 편집을 시험하려면 편집 도구를 **명시적으로 강제**한다
   (`Write 도구를 써서 ... Bash 쓰지 말고`).

## 현재 이식 상태

| 훅 | Claude | Codex | 비고 |
|---|---|---|---|
| `project-memory-index` | ✅ | ✅ | SessionStart — 커버리지 한계와 무관 |
| `memory-search` | ✅ | ✅ | `PreToolUse` / matcher `apply_patch`. 패치 원문에서 편집 파일 목록을 뽑아 라우팅 |
| `reflection` | ✅ | ✅ | `PostToolUse` / matcher `apply_patch`. 규칙은 **파일마다** 적용 |
| `pr-merge-reflect` | ✅ | ⬜ | 마지막 — LLM 잡·seen 캐시, Codex 세션에서 회고 중복 정리 필요 |

입력 정규화는 `core/scripts/hook_io.py` 가 맡는다 — Claude(`file_path` + `new_string`/`content`/
`edits`)와 Codex(`command` 에 담긴 패치 원문)를 **편집 파일 목록 + 추가된 내용**이라는 같은
모델로 바꾼다. 훅은 `tool_name` 으로 분기하지 않는다(툴마다 이름이 다르고 새로 생긴다).

**출력 키는 두 벌 낸다** — `hookSpecificOutput.additionalContext`(중첩)와 `additionalContext`
(최상위). Claude 는 중첩을 읽는다(실증). Codex 문서는 `PreToolUse`/`PostToolUse` 출력으로
`additionalContext` 를 나열하지만 **중첩인지 최상위인지 쓰지 않았고**, 중첩이 동작한 걸 확인한
건 `SessionStart` 뿐이다 — 그건 평문 stdout 도 먹는 이벤트라 중첩 경로를 시험한 적이 없다.
주입 실패는 성공과 구별이 안 되므로(훅은 조용히 exit 0) 관측 전까지 한쪽으로 줄이지 않는다.
