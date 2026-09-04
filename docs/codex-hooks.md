# Codex hooks — the official contract, plus what we measured

**The official documentation is the primary source.** This is a summary of it, with anything
we confirmed ourselves marked separately as **measured**.

- Official: <https://learn.chatgpt.com/docs/config-file/config-advanced>
- Checked: 2026-08-10 / codex-cli 0.145.0

> **Correction history:** the first two versions of this document were written from binary
> strings and by reverse-engineering rollout logs, and **got the tool names wrong** (asserted
> `exec`; the actual canonical names are `Bash` and `apply_patch`). The `exec` in the logs is
> an internal code-mode name, a different layer from hooks. Reading the docs first would have
> avoided it. Reverse-engineering is what you do when there is no documentation.

## Conclusion

Codex hooks are **nearly the same shape** as Claude's. A hook script body can run on both
sides largely untouched. What differs is the **coverage limits** and the **trust procedure**.

## Events

**Per turn:** `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`,
`UserPromptSubmit`, `SubagentStop`, `Stop`

**Per session:** `SessionStart`, `SubagentStart`, `SessionEnd` (⚠️ see below — firing unverified)

Compared to Claude there are extras: `PermissionRequest`, `PreCompact`/`PostCompact`,
`Stop`/`SubagentStop`, `SubagentStart`.

> **`SessionEnd` — listed, but firing unverified.** The official page above does not list
> `SessionEnd` among its events. Yet **Codex's `/hooks` screen shows it** (`Right before a
> session ends`, 0.145.0), and it appears in the binary's strings.
>
> But **we never observed it actually fire.** Appearing in `/hooks` means "this event is
> configurable", not "it is guaranteed to dispatch in our environment."
> **Observe it firing at least once before hanging cleanup work off it** — if it does not
> fire it does nothing silently, and a session-end hook that never runs leaves no trace.
>
> Generalizing the distinction: **enumerations** (lists of events) can be incomplete in the
> docs, so cross-checking against the real thing is cheap — but the result only tells you
> something *exists*. **Contracts** (tool names, input/output schemas) are where reverse
> engineering is especially dangerous — this document's earlier version mistaking the
> `tool_use_id` prefix `exec-` for a tool name is the example. And **"it works" is proven
> only by observing it fire.**

## Tool names (what `matcher` matches)

`matcher` is a **regex over the tool name**. Omitted, `"*"`, or `""` matches every occurrence.

| Name | Covers |
|---|---|
| `Bash` | shell commands |
| `apply_patch` | file edits — the matcher also accepts `Edit` and `Write` |
| `mcp__<server>__<tool>` | MCP tools |

⚠️ **The `exec` you see in rollout logs is not a hook tool name.** Measurement settled what it
is: the **`tool_use_id` prefix** in the hook input (`exec-9fa03e9a-13d8-...`). `tool_name`
arrives separately as `Bash` or `apply_patch`. Do not derive matcher values from logs.

Real input, abridged:

```json
{"hook_event_name":"PreToolUse","tool_name":"Bash",
 "tool_input":{"command":"echo hello"},
 "tool_use_id":"exec-c22ab2e4-ba2c-44ac-81c1-7f8d99969ef7"}

{"hook_event_name":"PreToolUse","tool_name":"apply_patch",
 "tool_input":{"command":"*** Begin Patch\n*** Add File: /tmp/x/test.txt\n+world\n*** End Patch"},
 "tool_use_id":"exec-9fa03e9a-13d8-438e-bb96-796a2717a0fe"}
```

**`apply_patch`'s `tool_input.command` is the raw patch text** — not a JS wrapper. Parse
`*** Begin Patch` / `*** Add File:` / `*** Update File:` / `*** Move to:` / `+` lines directly.
`PostToolUse` additionally carries `tool_response`.

## ⚠️ Coverage limits — the most important section

> `PreToolUse` and `PostToolUse` intercept **"simple" shell calls only**, not the newer
> `unified_exec` mechanism or tools like `WebSearch`. — *"doesn't intercept all shell calls yet"*

**Measured (2026-08-10, real user environment, code mode defaults):** both `PreToolUse` and
`PostToolUse` **fired normally.** Shell execution and `apply_patch` edits were both caught, and
matchers matched exactly.

| Action | `tool_name` | Matchers that matched |
|---|---|---|
| `echo hello` | `Bash` | no matcher, `Bash` |
| creating a file | `apply_patch` | no matcher, `apply_patch` |

So this limit **does not apply to ordinary shell and edit calls.** The docs do explicitly
exclude `unified_exec`, though, so environments using that path may still not be intercepted.
When porting, observe it once in the target environment — **it is easy to misdiagnose "did not
fire" as a matcher-name problem.**

## Input (stdin JSON)

**Common:** `session_id`, `transcript_path` (nullable), `cwd`, `hook_event_name`, `model`,
`permission_mode` (`default`|`acceptEdits`|`plan`|`dontAsk`|`bypassPermissions`)

**Added per turn:** `turn_id`

**Per event:**

| Event | Additional fields |
|---|---|
| `PreToolUse`/`PostToolUse` | `tool_name`, `tool_use_id`, `tool_input` (for Bash and apply_patch, an object with `command`) |
| `PermissionRequest` | `tool_name`, `tool_input` (optional `description`) |
| `SessionStart`/`SubagentStart` | `source` / `agent_type`, `agent_id` |
| `PreCompact`/`PostCompact` | `trigger` (`manual`\|`auto`) |
| `Stop`/`SubagentStop` | `stop_hook_active`, `last_assistant_message` |

## Output (stdout)

Common: `continue`, `stopReason`, `systemMessage`, `suppressOutput`

| Event | Event-specific output |
|---|---|
| `PreToolUse` | `permissionDecision` (`allow`\|`deny`) + `permissionDecisionReason`, `additionalContext`, `updatedInput` |
| `PostToolUse` | `decision: "block"` + `reason`, `additionalContext` |
| `UserPromptSubmit` | `decision: "block"` + `reason`; `additionalContext` becomes developer context |
| `SessionStart`/`SubagentStart` | plain stdout becomes developer context. `hookSpecificOutput.additionalContext` JSON also works |

Plain stdout is ignored for most events; it becomes context only for `SessionStart`,
`SubagentStart`, and `UserPromptSubmit`.

## Exit codes

| Code | Meaning |
|---|---|
| `0` + JSON | success, output parsed |
| `0` + no output | success, proceed unchanged |
| **`2`** | **block/deny** — reason goes on stderr |
| any other non-zero | reported as hook failure |

## Where configuration lives (in precedence order)

1. `~/.codex/hooks.json`, or `[hooks]` in `~/.codex/config.toml` (user)
2. `<repo>/.codex/hooks.json`, or `[hooks]` in `<repo>/.codex/config.toml` (project)
3. A plugin's bundled `hooks/hooks.json`, or the path its manifest names

When one layer has both a `hooks.json` and an inline `[hooks]`, they are merged with a warning.

A plugin registers via `"hooks": "./hooks/hooks.json"` in its manifest (measured).

Inline TOML form:

```toml
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/policy.py"'
timeout = 30
statusMessage = "Checking Bash command"
```

`$(git rev-parse --show-toplevel)` is **the idiom the docs themselves use**.

## Trust — without it, hooks are skipped silently

- **Project hooks** (`<repo>/.codex/`): load only once the `.codex/` layer is trusted, which
  requires explicit review. Trust is recorded **against the hook's hash**, so **changing the
  content re-triggers review**.
- **User/system hooks**: load from their own layer even when the project is untrusted. Same
  review and trust procedure.
- **Managed hooks** (`requirements.toml`, MDM, policy): trusted by policy; users cannot disable them.
- **Bypass**: `--dangerously-bypass-hook-trust` (only for hooks you have verified).

⚠️ An untrusted hook is skipped **with no error and no warning**. The install looks successful,
so this must be part of any user-facing instructions.

### `codex exec` (non-interactive) + a **not-yet-trusted** hook = no response

Trust is **stored against the hook's hash** (above), so an already-trusted hook just runs
non-interactively — we confirmed this repository's installed plugin hooks running under a plain
`codex exec` with no flags.

The problem is a hook that has **no trust yet**: a newly written `.codex/hooks.json`, or a hook
whose **content changed** after being trusted. In that case `codex exec` **hangs indefinitely
with no output.** It appears to be waiting on trust with no terminal to render the approval
screen.

Measured 2026-08-18, codex-cli 0.147.0. Same prompt, one variable changed:

| Condition | Result |
|---|---|
| empty directory (installed plugin hooks only, **trusted**) | responded in seconds, hooks ran |
| freshly written `.codex/hooks.json` (**untrusted**, body is one `echo`) | no output after 100+ seconds |
| the above + `--dangerously-bypass-hook-trust` | responded in seconds, hooks ran |

The hook body is an `echo` that does nothing. **The absence of trust** is the condition, not
what the hook does.

**Telling this apart from "just slow":** a successful `codex exec` leaves a rollout log under
`~/.codex/sessions/<date>/`. A hung run **leaves no log at all** — it stopped before the session
began.

**How to resolve it, in order:**

1. **Open interactive `codex` once and trust the hook.** Non-interactive runs then work with no
   flags. Because trust is hash-based, this has to be **redone every time you edit the hook**.
2. Use `--dangerously-bypass-hook-trust` only in automation where no human can approve (CI).

⚠️ **Do not make that flag the default for non-interactive runs.** It disables provenance
verification of hooks, and it will **let through a hook whose content changed without your
knowledge** — precisely the situation the trust procedure exists to catch. Use it only for hooks
you wrote or whose provenance you verified.

⚠️ Trying to test hook behavior with this flag gave mixed results — some hooks did not fire even
with it, and one still hung. The conditions under which project hooks actually run under
`codex exec` are still unknown ([#114](https://github.com/foxyberry/agent-harness/issues/114)).
**Do not trust it as an environment for testing whether hooks fire.** What this flag fixes is
the hang, and only that.

## Loud failure — a hook blocking tool calls

Hooks fail in two ways. Knowing only the **quiet** one above (untrusted → silent skip) means
looking in the wrong place when you meet the loud one.

**If `command` exits 2, that tool call is blocked.** That is the contract (see the exit code
table). The problem is that there are **paths where 2 arrives unintentionally.**

```
$ python3 /nonexistent/path.py ; echo $?
2
```

`python3` exits **2** when it cannot open a file — **the same number** as the hook contract's
"block". So when `command` is a bare `python3 <path>`, Python's *"I can't open that file"*
reaches Codex as *"deny this command."*

It happened ([#107](https://github.com/foxyberry/agent-harness/issues/107)). Updating a plugin
deletes the old version's cache directory, and **a session started before the update keeps
pointing at that path.** Every shell command in that session was blocked:

```
ERROR Command blocked by PreToolUse hook:
  can't open file '.../agent-harness/0.7.1/hooks/memory-search.py': No such file or directory
```

The symptom does not point at the cause — the error names the hook script, and the path carries
a version number that no longer exists, so it reads like a corrupted file. Nothing suggests
"you updated the plugin a minute ago."

**The fix:** wrap `command` in a shell guard. In this repository `hook_command()` in `build.sh`
generates every one of them this way.

```sh
p="${CLAUDE_PLUGIN_ROOT}/hooks/<script>"; if [ -f "$p" ]; then python3 "$p"; fi
```

| Case | exit | Result |
|---|---|---|
| script missing | `0` | passes quietly — nothing blocked |
| normal | `0` + output | unchanged |
| hook deliberately exits 2 | `2` | **blocking still works** |
| hook bug exits 1 | `1` | reported as failure, proceeds |

⚠️ **It has to be the `if` form.** The common `python3 "$p" || exit 0` also handles the missing
file, but it **swallows a deliberate exit 2 as well.** No hook blocks anything today so nothing
would look wrong, but the first one that does would be silently disarmed. The `if` form passes 1
and 2 through untouched.

**In practice this risk is Codex-side** — the two tools clean up caches in opposite ways
(measured 2026-08-17).

| | Cache after updating 0.8.0 → 0.8.1 |
|---|---|
| Claude | `0.6.0` `0.7.0` `0.7.1` `0.8.0` `0.8.1` `56a1882` — **keeps old versions** |
| Codex | `0.8.1` alone — **deletes old versions** |

On the Claude side even `0.6.0` and `0.7.1`, which nothing references, are still there — so it
is not reference counting, it simply keeps them. An update therefore leaves **a running
session's paths still valid**, and no dangling path appears. On Codex, `0.8.0` was actually gone.

The guard goes in on **both sides** regardless. Claude's retention is an observation, not a
documented contract, and we would have no way to learn if it changed. The guard costs nothing,
so it does not lean on the observation.

`tests/test_hook_wiring.py` enforces this — it takes the registered `command` strings and
**runs them in a shell**, checking that a missing script does not produce exit 2.

## Environment variables

**Plugin hooks:** `PLUGIN_ROOT`, `PLUGIN_DATA` (Codex-specific) plus `CLAUDE_PLUGIN_ROOT`,
`CLAUDE_PLUGIN_DATA` (**compatibility aliases**)

**All hooks:** the session `cwd` is set as the working directory.

⚠️ **`CLAUDE_PROJECT_DIR` is not provided** (measured). Get the project path from `cwd` in the
input JSON. The process cwd is not the plugin root, so a **relative-path `command` fails**
(measured) — use an absolute path based on `${CLAUDE_PLUGIN_ROOT}`, or the docs'
`$(git rev-parse ...)` idiom.

The canonical version of this resolution order is `project_dir(data)` in
`core/scripts/hook_io.py`. Use that helper rather than re-implementing the fallback in each
hook. `build.sh` copies `hook_io.py` into both adapters' hook directories.

## Other constraints

- Only `type: "command"` runs. `prompt` and `agent` types are parsed and skipped.
- Async command hooks are parsed but not executed.
- Default timeout is 600 seconds, adjustable with `timeout` (seconds).
- Several hooks matching the same event run **concurrently** and cannot block each other.
- `PreToolUse` is not a complete enforcement point — it can be bypassed with another tool.

## How to verify injection (reproducible)

Whether a hook actually injected context **must be distinguished from the model simply reading
the file itself.** Put a canary string only in `.claude/memory/INDEX.md` and run twice, hooks off
and on.

```bash
export CODEX_HOME=<isolated path>        # keep the real ~/.codex clean
codex plugin marketplace add <repo>
codex plugin add agent-harness@foxyberry

P="If the context given at session start contains a canary, print only that. Do not read files. If not, print NONE."
codex exec "$P"                                    # control (hooks ignored) → NONE
codex exec --dangerously-bypass-hook-trust "$P"    # treatment (hooks run)  → CANARY
```

The measured results split as `NONE` / `SPIKE_CANARY_12345`. **Without "do not read files" the
model just reads it and the experiment means nothing.**

⚠️ **Do not copy `auth.json` into the isolated `CODEX_HOME`.** The refresh token is single-use;
it will race with the original and can break both. Run `codex login` separately in the isolated
home.

Do this in a project **outside** the harness repo ([[adapter-cross-project-testing]]).

## Catching silent failures (issue #85, stage 4)

When a hook does not run, nothing happens on screen — because "did not run" and "ran and had
nothing to say" look identical from outside. So it is checked in two layers.

### 1. Inside the repository — wiring tests

`tests/test_hook_wiring.py` reads `plugins/*/hooks/hooks.json` and checks:

| Failure mode | How it is caught |
|---|---|
| typo in a hooks.json path | is the registered script actually in that bundle |
| missing helper copy (`hook_io`, `repo_identity`) | run the registered hook **from the bundle directory** and check exit 0 |
| matcher mismatch | do the matchers cover the measured tool names (`Edit`/`Write`/`MultiEdit`/`Bash`, `apply_patch`/`Bash`) |
| normalization works but the hook never fires | does the edit hook's matcher accept the edit fixture's `tool_name` |

The tool-name list is not derived from the matchers — that would be the check examining itself
and would catch nothing. Its source is the measured table in this document.

These tests read generated files (`plugins/*/hooks/hooks.json`), so they fail if `./build.sh`
was not run. That is not a breakage; it is build-drift detection.

### Why we need our own instrumentation — tool logs are not enough

Can't we tell whether a hook ran from the logs the tools write? We measured it (2026-08-15,
`tutti-dpnc`).

**Codex rollout logs**: contain **no record of hook execution at all.** Text a hook injected
becomes part of the conversation, but neither which hook put it there nor the fact that a hook
ran survives.

**Claude session `.jsonl`**: does record them. `type: attachment` entries carry `hookEvent` and
the hook's raw stdout. But **only some of them** — compared against a trace from the same session:

| Event | Actually fired (trace) | Claude log |
|---|---|---|
| SessionStart | 2 | 3 |
| UserPromptSubmit | 3 | 0 |
| PreToolUse | 3 | 0 |
| PostToolUse | 3 | 1 |

What the missing ones have in common is that they are **runs that ended quietly with nothing to
inject.** `memory-search` fired all three times but matched no route, produced nothing, and so
was not recorded. Circumstantially it appears **only runs that produced output** are logged (we
did not confirm the rule itself; it is not filtering by event type, though — `PostToolUse` is a
logged event and still only 1 of 3 survived).

**Conclusion:**

| What you want to know | Codex log | Claude log | `HARNESS_HOOK_TRACE` |
|---|---|---|---|
| it ran and injected something | inferable | ✅ | ✅ |
| it ran but stayed quiet | ❌ | ❌ | ✅ |
| it never ran | ❌ | ❌ | ✅ |

Neither log **distinguishes "ran quietly" from "never ran"** — which is exactly the failure mode
we missed for three weeks. The Claude log is a partial substitute, but it **cannot prove absence.**

### 2. Outside the repository — entry tracing (`HARNESS_HOOK_TRACE`)

Whether an installed copy is skipped for being untrusted, and whether the tool really launches
hooks, are **install-state and runtime** questions this repository's tests cannot see. Observe
them in a target project.

Point `HARNESS_HOOK_TRACE` at a path and every registered hook appends one JSONL line **on
entry**. Writing it on entry rather than in `emit_context` is the whole point — logging at
injection time would again collapse "ran but matched no route" and "never ran" into the same
thing, distinguishing nothing. With the variable unset it does nothing (zero everyday cost).

```bash
export HARNESS_HOOK_TRACE=/tmp/hook-trace.jsonl
rm -f "$HARNESS_HOOK_TRACE"
codex          # or claude — in a project outside the harness repo
# inside the session: one shell command (`echo hi`) and one file edit
cat /tmp/hook-trace.jsonl
```

Expected — at least one line per registered (event, hook) pair:

| Tool | Lines that must appear |
|---|---|
| Codex | `project-memory-index` (SessionStart), `memory-search` (PreToolUse ×2), `reflection` (PostToolUse), `pr-merge-reflect` (SessionStart, PostToolUse/Bash — pending install smoke test) |
| Claude | the three edit/index hooks above, plus `pr-merge-reflect` (SessionStart, UserPromptSubmit, PostToolUse) |

A hook with **no** line is a silent failure. There are three causes — the plugin is untrusted
(→ [Trust](#trust--without-it-hooks-are-skipped-silently)), a matcher mismatch (→ the wiring
tests above), or the installed copy is an old version (→ check the install path and version).

### Observed results (2026-08-15, `tutti-dpnc` — outside the harness repo)

Plugin 0.7.1. **Every registered hook on both adapters actually fired.**

| Hook | Claude | Codex |
|---|---|---|
| `project-memory-index` (SessionStart) | ✅ | ✅ |
| `memory-search` (PreToolUse — shell and edit) | ✅ | ✅ |
| `reflection` (PostToolUse — edit) | ✅ | ✅ |
| `pr-merge-reflect` | ✅ (three events) | 🟡 SessionStart and PostToolUse registered, install measurement pending |

`HARNESS_HOOK_TRACE` **propagates into hook subprocesses on both sides** (Codex needs no extra
setup).

**Controls came out too** — that is what makes "everything fired" evidence rather than a claim.

- Claude: in the round that used Write, `pr-merge-reflect`'s PostToolUse **did not fire** (its
  matcher is `Bash`). It fired only in the Bash round.
- Codex: on a shell call, `reflection` **did not fire** (its matcher is `apply_patch`). It fired
  only on the edit.

⚠️ **A trace line does not confirm the version.** A line tells you "code with the instrumentation
is installed" and no more. Version is a separate check — `befd775` is precisely the commit that
added `trace_entry` **while the manifest still said 0.7.0**, so a build that reports 0.7.0 and
carries the tracing code genuinely exists (a local build, or a release without a version bump).
Confirm the version separately from the cache directory name or `plugin list`.

### Two traps we walked into while observing

1. **The PR that added the instrumentation (#101) did not bump the version, so no installed copy
   anywhere had it.** Observing as-is would have produced 0 lines and been misread as "hooks do
   not fire." The trap #101 set out to catch is the one #101 fell into. → Before observing,
   **grep the install cache for `trace_entry` first.**
2. **The first attempt was not a valid experiment.** Asked to "create a file", the session
   created it via the shell and never used an edit tool, so `reflection` never fired. We only
   found out after checking the session log and seeing two `tool=Bash` calls and nothing else.
   **It was a test-design problem, not a hook problem** — and it is the easiest misdiagnosis to
   make while investigating a silent failure. To test edits, **explicitly force the edit tool**
   ("use the Write tool to ..., do not use Bash").

## Current porting status

| Hook | Claude | Codex | Notes |
|---|---|---|---|
| `project-memory-index` | ✅ | ✅ | SessionStart — unaffected by the coverage limits |
| `memory-search` | ✅ | ✅ | `PreToolUse` / matcher `apply_patch`. Extracts the edited file list from the raw patch to route on |
| `reflection` | ✅ | ✅ | `PostToolUse` / matcher `apply_patch`. Rules apply **per file** |
| `pr-merge-reflect` | ✅ | 🟡 | Stage 3a: SessionStart and PostToolUse detection/queueing only. UserPromptSubmit injection and the LLM job stay unregistered until measured |

The Codex 3a bundle deliberately omits `reflect.py`. It can therefore detect merges and session
starts and update the shared queue, but it will not immediately draft a retrospective from an
in-progress Codex rollout, nor drain the queue from the still-unverified `UserPromptSubmit`. The
final registration opens once both event firing and context injection are observed in a real
installed copy ([#85](https://github.com/foxyberry/agent-harness/issues/85)).

Input normalization is `core/scripts/hook_io.py`'s job — it turns Claude's shape (`file_path`
plus `new_string`/`content`/`edits`) and Codex's (raw patch text inside `command`) into one model:
**the list of edited files plus the added content**. Hooks do not branch on `tool_name` (the names
differ per tool and new ones appear).

**Output keys are emitted twice** — as `hookSpecificOutput.additionalContext` (nested) and as
`additionalContext` (top level). Claude reads the nested one (demonstrated). The Codex docs list
`additionalContext` as `PreToolUse`/`PostToolUse` output but **do not say whether it is nested or
top level**, and the only event where we confirmed the nested form working is `SessionStart` —
which also accepts plain stdout, so the nested path was never really exercised there. A failed
injection is indistinguishable from a successful one (the hook just exits 0 quietly), so we do
not narrow to one form before observing it.
