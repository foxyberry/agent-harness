# Codex 훅 — 실측 정리 (codex-cli 0.145.0)

이 문서는 **추측이 아니라 실제로 돌려서 확인한 것**만 적는다. 예전에 "Codex 훅은 버전 취약으로
defer"라고 적어뒀는데, 지금 기준으로 사실이 아니어서 다시 조사했다.

## 결론

Codex 는 훅을 정식 지원하고, **플러그인으로 배포할 수 있으며, 형식이 Claude 와 거의 같다.**
훅 스크립트 본문은 대부분 손대지 않고 양쪽에서 돌릴 수 있다.

## Claude 와 같은 것

| 항목 | 내용 |
|---|---|
| 이벤트 이름 | `PreToolUse`, `PostToolUse`, `SessionStart`, `UserPromptSubmit` (+ Codex 전용 `PermissionRequest`, `SubagentStart`) |
| `hooks.json` 구조 | `{"hooks": {"<이벤트>": [{"hooks": [{"type": "command", "command": "..."}]}]}}` |
| 입력 (stdin JSON) | `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`, `permission_mode`, `source` |
| 출력 | `hookSpecificOutput` + `additionalContext` |
| **`${CLAUDE_PLUGIN_ROOT}`** | **Codex 도 세팅한다.** `PLUGIN_ROOT` 도 같은 값으로 함께 준다 |

`CLAUDE_PLUGIN_ROOT` 를 Codex 가 준다는 건 값으로 확인했다 — 값이 Codex 플러그인 캐시 경로
(`$CODEX_HOME/plugins/cache/<marketplace>/<plugin>/<version>`)를 가리켰고, 실행한 셸에는 그
변수가 없었다. 호환 별칭을 의도적으로 제공하는 것으로 보인다. `CLAUDE_PLUGIN_DATA` /
`PLUGIN_DATA` 도 마찬가지로 주어진다.

## Claude 와 다른 것 — 여기서 걸린다

**1. `CLAUDE_PROJECT_DIR` 을 안 준다**

프로젝트 루트는 **입력 JSON 의 `cwd`** 에서 얻어야 한다. 훅 스크립트는 이렇게 쓴다:

```python
def _project_dir(data=None):
    return (os.environ.get("CLAUDE_PROJECT_DIR")     # Claude
            or (data or {}).get("cwd")               # Codex
            or os.getcwd())                          # 최후 수단
```

**2. 상대경로 `command` 는 실패한다**

프로세스 cwd 가 **사용자 프로젝트**다(플러그인 루트가 아니다). `python3 hooks/foo.py` 는
`hook: SessionStart Failed` 로 끝난다. 반드시 `${CLAUDE_PLUGIN_ROOT}` 기준 절대경로로 쓴다.

**3. 훅 신뢰(trust)를 등록해야 한다 — 안 하면 조용히 무시**

이게 배포 관점에서 가장 중요하다. 신뢰 등록 전에는 **에러도 경고도 없이 그냥 안 돈다.**
설치했는데 아무 일도 안 일어나는 것처럼 보인다.

- 확인/등록: `hook_trust`, `hook_sources` 설정
- 자동화용 우회: `codex --dangerously-bypass-hook-trust` (이름 그대로 위험 — 검증된 훅에만)

Claude 에는 없는 단계이므로 **사용자 안내에 반드시 포함**해야 한다.

**4. `matcher` 는 동작하지만 도구 이름이 Claude 와 다르다** ⚠️

`matcher` 는 Codex 도 **정상 지원한다.** 절대 매칭될 수 없는 값(`ZZZ_NEVER_MATCHES`)을 걸고
셸 명령을 실행시켰더니 훅이 뜨지 않았다 — 무시되는 게 아니라 제대로 걸러진다.

문제는 **도구 이름**이다. Claude 의 `Edit`·`Write`·`Bash` 를 그대로 쓰면 하나도 안 맞는다.
실제 Codex 세션 rollout 에서 도구는 `exec`(`custom_tool_call`) 하나로 나온다.

```
name='exec'  type='custom_tool_call'
input=const r = await tools.exec_command({cmd:"..."})
```

`apply_patch` 도 **도구 이름이 아니다** — `cmd` 문자열 안의 텍스트로만 등장한다.

즉 도구별 필터가 필요한 훅(`memory-search`, `reflection`)은 matcher 값을 Codex 도구 이름으로
바꾸거나, matcher 를 빼고 **입력의 `tool_name` 을 스크립트가 직접 보고 거르도록** 해야 한다.

**매칭 안 된 훅은 완전히 무음이다** — 에러도 경고도 없다. hooks.json 은 잘 등록됐고 `/hooks`
에도 보이는데 실제로는 안 도는 상태가 되므로, 이식할 때 반드시 실측으로 확인한다.

> 여기 적힌 `exec` 는 rollout 로그에 기록된 이름이다. 훅 입력의 `tool_name` 필드가 같은
> 문자열인지는 아직 직접 확인하지 못했다. 이식 전에 matcher 없는 임시 훅으로 `tool_name` 을
> 한 번 찍어 확정할 것.
>
> **정정 이력:** 최초 작성 때 "Codex 에 `matcher` 키가 없다"고 적었다. 바이너리 문자열에서
> `"matcher"` 를 못 찾은 것만 근거로 삼은 잘못된 단정이었다. 실제로 돌려보니 지원한다.
> 부재는 grep 으로 증명되지 않는다.

## 검증 방법 (재현용)

훅이 실제로 컨텍스트를 주입했는지는 **모델이 파일을 직접 읽어서 답한 것과 구별해야** 한다.
canary 문자열을 `.claude/memory/INDEX.md` 에만 두고, 같은 프롬프트로 훅 켬/끔 두 번 돌린다.

```bash
export CODEX_HOME=<격리 경로>            # 실제 ~/.codex 오염 방지
codex plugin marketplace add <repo>
codex plugin add agent-harness@foxyberry

P="세션 시작 시 주어진 컨텍스트에 canary 가 있으면 그것만 출력. 파일 읽지 마. 없으면 NONE."
codex exec "$P"                                    # 대조군(훅 무시) → NONE
codex exec --dangerously-bypass-hook-trust "$P"    # 실험군(훅 실행) → CANARY
```

실측 결과가 정확히 `NONE` / `SPIKE_CANARY_12345` 로 갈렸다. **"파일을 읽지 마"를 넣지 않으면
모델이 그냥 INDEX.md 를 읽어버려서 실험이 무의미해진다** — 이 대조가 없으면 주입을 증명한 게
아니다.

검증은 harness repo **밖**의 별도 프로젝트에서 한다([[adapter-cross-project-testing]]).

## 현재 이식 상태

| 훅 | Claude | Codex | 비고 |
|---|---|---|---|
| `project-memory-index` | ✅ | ✅ | 스파이크로 이식 완료 |
| `memory-search` | ✅ | ⬜ | matcher 값을 Codex 도구 이름으로 바꿔야 함. 먼저 `tool_name` 실측 |
| `reflection` | ✅ | ⬜ | 위와 동일 |
| `pr-merge-reflect` | ✅ | ⬜ | 마지막에 — LLM 잡을 띄우고 seen 캐시를 쓴다. Codex 세션에서 Codex 회고를 또 띄우는 중복도 정리해야 함 |
