#!/usr/bin/env bash
# core/ (the canonical templates) → rendered into each tool adapter. Rendering instead of
# symlinks keeps this cross-platform and lets the wording be exact per tool.
# Always run this after changing core/ and commit the generated output too. CI checks for drift.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Replace {{PLACEHOLDER}} in SKILL.md with the per-adapter value (sed delimiter | — values may contain /)
render() { # $1=src  $2=dst   (env: AGENT RULES_FILE HANDOFF DEEP_RECOVERY PATH_NOTE PERSONAL_TIER_NOTE PROJECT_DIR_ARG)
  sed -e "s|{{AGENT}}|$AGENT|g" \
      -e "s|{{RULES_FILE}}|$RULES_FILE|g" \
      -e "s|{{HANDOFF}}|$HANDOFF|g" \
      -e "s|{{COMPACT}}|$COMPACT|g" \
      -e "s|{{DEEP_RECOVERY}}|$DEEP_RECOVERY|g" \
      -e "s|{{PATH_NOTE}}|$PATH_NOTE|g" \
      -e "s|{{PERSONAL_TIER_NOTE}}|$PERSONAL_TIER_NOTE|g" \
      -e "s|{{PROJECT_DIR_ARG}}|$PROJECT_DIR_ARG|g" \
      -e "s|{{FW_FROM_DEFAULT}}|$FW_FROM_DEFAULT|g" \
      -e 's/[[:blank:]]*$//' \
      "$1" > "$2"
}

# A hook command must **do nothing and exit 0 when the script is missing**.
# python3 exits 2 when it cannot open the file, and in the hook contract 2 means "block
# this tool call". So when a plugin update deletes the old version's cache directory,
# every shell command of a session still pointing there gets blocked — Python's "cannot
# open the file" is delivered verbatim as "deny" (#107).
#
# ⚠️ It must be the `if` form. `python3 "$p" || exit 0` also covers the missing file, but
# it **swallows an exit 2 the hook raised on purpose**, silently defeating any blocking
# hook we may add later. `if` passes 1 and 2 through, so there is no need to audit which
# hook is doing the blocking.
hook_command() {  # $1 = hook script filename → shell command, escaped for a JSON string
  printf 'p=\\"${CLAUDE_PLUGIN_ROOT}/hooks/%s\\"; if [ -f \\"$p\\" ]; then python3 \\"$p\\"; fi' "$1"
}

SKILLS=$(cd core/skills && ls -d */ | sed 's#/##')

# ── Claude adapter: plugins/harness ────────────────────────────
# Scripts are shared through bin/ (registered on PATH while the plugin is active — verified).
rm -rf plugins/harness/skills plugins/harness/bin plugins/harness/hooks
mkdir -p plugins/harness/bin
cp core/scripts/handoff.py plugins/harness/bin/agent-handoff
# repo_identity: agent-handoff imports it from dirname(__file__)=bin/ (co-location convention).
cp core/scripts/repo_identity.py plugins/harness/bin/repo_identity.py
# The retrospective skill needs a compacted transcript when it uses past sessions as
# candidates (originals are several MB). The hooks bundle the same file, but skills do not
# reference hooks/ — same co-location convention as repo_identity.
cp core/hooks/compact_transcript.py plugins/harness/bin/compact_transcript.py
# ⚠️ chmod comes **after** cp. chmod on a missing file stops build.sh right there.
chmod +x plugins/harness/bin/agent-handoff plugins/harness/bin/compact_transcript.py
AGENT=claude; RULES_FILE=CLAUDE.md; HANDOFF=agent-handoff; COMPACT=compact_transcript.py
DEEP_RECOVERY='`/fw --from claude` or `/fw-both`'   # only commands that really exist (naming a non-existent one invites manual digging — issue #95)
PATH_NOTE=''   # Claude: bin/ is on PATH, so the cwd does not matter
PERSONAL_TIER_NOTE=''   # Claude: auto-memory loads the personal tier by itself — no note needed
PROJECT_DIR_ARG=''   # Claude: resolved automatically from the CLAUDE_PROJECT_DIR env var — no argument needed
FW_FROM_DEFAULT='codex'   # Claude fw restores the other tool's (codex) logs — prevents the current Claude session from selecting itself
for s in $SKILLS; do
  mkdir -p "plugins/harness/skills/$s"
  render "core/skills/$s/SKILL.md" "plugins/harness/skills/$s/SKILL.md"
done

# Hooks: bundle core/hooks/*.py as is (scripts co-located — a hook finds reflect.py via
# dirname(__file__), and reflect.py finds compact_transcript.py). Python is generic, so no
# placeholder rendering is needed. hooks.json references this bundle via ${CLAUDE_PLUGIN_ROOT}.
# ⚠️ Codex hooks were not included in pass 1 (version-fragile: openai/codex#19385, #21639)
# — only skills shipped to both. (issue #1)
mkdir -p plugins/harness/hooks
cp core/hooks/*.py plugins/harness/hooks/
# repo_identity lives in core/scripts, but the pr-merge-reflect hook imports it too → co-locate it in hooks/ as well.
cp core/scripts/repo_identity.py plugins/harness/hooks/repo_identity.py
# hook_io: the edit hooks (memory-search, reflection) use it for input normalization and
# output emission. Co-located under the same convention.
cp core/scripts/hook_io.py plugins/harness/hooks/hook_io.py
chmod +x plugins/harness/hooks/*.py
{
  printf '%s\n' '{'
  printf '%s\n' '  "hooks": {'
  printf '%s\n' '    "PreToolUse": ['
  printf '      { "matcher": "Edit|Write|MultiEdit|Bash", "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command memory-search.py)"
  printf '%s\n' '    ],'
  printf '%s\n' '    "PostToolUse": ['
  printf '      { "matcher": "Edit|Write|MultiEdit", "hooks": [ { "type": "command", "command": "%s" } ] },\n' "$(hook_command reflection.py)"
  printf '      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command pr-merge-reflect.py)"
  printf '%s\n' '    ],'
  printf '%s\n' '    "SessionStart": ['
  printf '      { "hooks": [ { "type": "command", "command": "%s" } ] },\n' "$(hook_command project-memory-index.py)"
  printf '      { "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command pr-merge-reflect.py)"
  printf '%s\n' '    ],'
  printf '%s\n' '    "UserPromptSubmit": ['
  printf '      { "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command pr-merge-reflect.py)"
  printf '%s\n' '    ]'
  printf '%s\n' '  }'
  printf '%s\n' '}'
} > plugins/harness/hooks/hooks.json

# ── Codex adapter: plugins/codex/ (skill-only plugin) ──────────
# Aligned with the canonical convention (plugins/<name>) — same location as the OpenAI
# marketplace and the Claude adapter (issue #4).
# Scripts are bundled inside each skill folder (scripts/) to avoid assuming a bin PATH
# (unverified territory on Codex).
rm -rf plugins/codex/skills plugins/codex/bin
AGENT=codex; RULES_FILE=AGENTS.md; HANDOFF='python3 scripts/handoff.py'
COMPACT='python3 scripts/compact_transcript.py'
# The old value was "the most recent session log in `~/.codex/sessions`" — that tells the
# user to dig through the folder by hand. Manual digging has no project scoping, so it can
# pick up a session from someone else's project (issue #95).
DEEP_RECOVERY='`/fw --from codex` or `/fw-both`'
# Codex: the paths above are relative to the skill folder holding this SKILL.md — run them
# after cd'ing into that folder. The script locates the project via the git root of the cwd,
# and the skill folder (a plugin cache) may be outside the user repository, so the user
# project must always be named explicitly with --project-dir. (Same convention as OpenAI's
# bundled skills: "cd to plugin root + absolute path argument". Without this argument the
# handoff is saved in the wrong place — issue #3.)
PATH_NOTE='> Paths under `scripts/` are relative to **the skill directory containing this SKILL.md**. Run the commands from that directory. Replace the `--project-dir` value with **the absolute path of the user project you are working on**. The skill may be in a plugin cache outside that repository; omitting this argument can select the wrong project.'
# Put --project-dir into the Codex command examples themselves (a footnote alone gets lost
# when the command is copy-pasted — raised in review). Keep the trailing space.
PROJECT_DIR_ARG='--project-dir "<absolute-path-to-user-project>" '
FW_FROM_DEFAULT='claude'   # Codex fw restores the other tool's (claude) logs — prevents the current Codex session from selecting itself
# Codex: the personal-tier path belongs to Claude auto-memory — Codex cannot load it automatically in a later session
PERSONAL_TIER_NOTE='  > In Codex, this personal-tier path belongs to **Claude auto-memory**; this harness does not automatically reload it into later Codex sessions. If Codex also needs an item, assess whether it belongs in shared committed memory with an INDEX.md entry. Respect the project privacy and tier rules; do not publish personal information merely to make it available across tools.'
for s in $SKILLS; do
  mkdir -p "plugins/codex/skills/$s/scripts"
  # Every remaining skill uses handoff.py (the exceptions, merge-cleanup and prettier-guard,
  # moved to personal scope).
  cp core/scripts/handoff.py "plugins/codex/skills/$s/scripts/handoff.py"
  # handoff.py imports it from the same folder — ship it wherever handoff.py is bundled.
  cp core/scripts/repo_identity.py "plugins/codex/skills/$s/scripts/repo_identity.py"
  cp core/hooks/compact_transcript.py "plugins/codex/skills/$s/scripts/compact_transcript.py"
  render "core/skills/$s/SKILL.md" "plugins/codex/skills/$s/SKILL.md"
done

# ── Codex hooks ────────────────────────────────────────────────
# Verified (codex 0.145.0): the plugin manifest's "hooks" key points at hooks.json, and
# Codex **sets `CLAUDE_PLUGIN_ROOT` as a compatibility alias** → hooks.json uses the same
# format as Claude. It does not provide `CLAUDE_PROJECT_DIR` though — hook scripts locate
# the project from `cwd` in the input JSON.
# ⚠️ A relative-path command fails (the process cwd is the user project). Always anchor on
# ${CLAUDE_PLUGIN_ROOT}.
# ⚠️ Until the user registers hook trust, Codex **silently ignores** hooks (no error).
# Matchers use **measured tool names**: file edits = `apply_patch`, shell = `Bash` (0.145.0).
# The `exec` seen in rollout logs is a tool_use_id prefix, not a tool name — do not derive
# names from the logs. The docs claim `Edit|Write` is accepted as a matcher too, but we only
# use names we measured.
# pr-merge-reflect phase 3a: register only the SessionStart/PostToolUse detect-and-queue
# steps. UserPromptSubmit stays unregistered because clearing pending before injection is
# measured as working would lose the notification. reflect.py is not bundled either, which
# structurally closes the path to immediate, duplicated auto-retrospectives during a live
# Codex rollout (#85).
rm -rf plugins/codex/hooks
mkdir -p plugins/codex/hooks
cp core/hooks/project-memory-index.py core/hooks/memory-search.py core/hooks/reflection.py \
   core/hooks/pr-merge-reflect.py \
   plugins/codex/hooks/
# The edit hooks import these from dirname(__file__) — ship them wherever the hooks are bundled.
cp core/scripts/hook_io.py plugins/codex/hooks/hook_io.py
cp core/scripts/repo_identity.py plugins/codex/hooks/repo_identity.py
chmod +x plugins/codex/hooks/*.py
{
  printf '%s\n' '{'
  printf '%s\n' '  "hooks": {'
  printf '%s\n' '    "PreToolUse": ['
  printf '      { "matcher": "apply_patch|Bash", "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command memory-search.py)"
  printf '%s\n' '    ],'
    printf '%s\n' '    "PostToolUse": ['
  printf '      { "matcher": "apply_patch", "hooks": [ { "type": "command", "command": "%s" } ] },\n' "$(hook_command reflection.py)"
  printf '      { "matcher": "Bash", "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command pr-merge-reflect.py)"
  printf '%s\n' '    ],'
  printf '%s\n' '    "SessionStart": ['
  printf '      { "hooks": [ { "type": "command", "command": "%s" } ] },\n' "$(hook_command project-memory-index.py)"
  printf '      { "hooks": [ { "type": "command", "command": "%s" } ] }\n' "$(hook_command pr-merge-reflect.py)"
  printf '%s\n' '    ]'
  printf '%s\n' '  }'
  printf '%s\n' '}'
} > plugins/codex/hooks/hooks.json

# Post-render guard against unsubstituted placeholders — only SKILL.md is checked.
# (Other files contain legitimate double braces that would be flagged as placeholders;
#  placeholders are a SKILL.md-only concept.)
if grep -rl --include='SKILL.md' '{{' plugins/harness/skills plugins/codex/skills 2>/dev/null | grep -q .; then
  echo "ERROR: unsubstituted placeholder left"; grep -rn --include='SKILL.md' '{{' plugins/harness/skills plugins/codex/skills; exit 1
fi
echo "Build complete: core → Claude (plugins/harness, bin on PATH) + Codex (plugins/codex, scripts bundled per skill)"
