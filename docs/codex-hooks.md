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

**세션 단위:** `SessionStart`, **`SessionEnd`**, `SubagentStart`

Claude 대비 `PermissionRequest`·`PreCompact`/`PostCompact`·`Stop`/`SubagentStop`·`SubagentStart`
가 더 있다.

> **문서와 실물이 어긋난 지점:** 위 공식 문서 페이지의 이벤트 목록에는 `SessionEnd` 가 없지만
> 바이너리에는 있다(0.145.0 실측). 확인 방법:
>
> ```bash
> BIN=$(find "$(npm root -g)/@openai/codex" -name codex -type f -size +1M | head -1)
> strings "$BIN" | grep -oE '"(PreToolUse|SessionStart|SessionEnd|Stop|...)"' | sort -u
> ```
>
> 문서가 1차 출처인 건 맞지만 **완전하지 않을 수 있다.** 이벤트 목록처럼 열거형인 항목은
> 실물로 교차 확인하는 게 값싸다. 반대로 도구 이름·스키마처럼 **계약**에 해당하는 건
> 실물 역추론이 위험하다(내부 이름과 공개 이름이 다름) — 문서를 따른다.

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

## 현재 이식 상태

| 훅 | Claude | Codex | 비고 |
|---|---|---|---|
| `project-memory-index` | ✅ | ✅ | SessionStart — 커버리지 한계와 무관 |
| `memory-search` | ✅ | ⬜ | **이식 가능 확정.** `apply_patch` matcher, `tool_input.command` 에서 패치 파싱 |
| `reflection` | ✅ | ⬜ | 위와 동일 (`PostToolUse`) |
| `pr-merge-reflect` | ✅ | ⬜ | 마지막 — LLM 잡·seen 캐시, Codex 세션에서 회고 중복 정리 필요 |
