#!/usr/bin/env python3
"""
Session transcript (.jsonl) -> compact markdown for retrospection input.
Auto-detects and supports both formats: Claude Code and Codex rollout
(`~/.codex/sessions/.../rollout-*.jsonl`).

Keeps only the signal a retrospective needs:
  - every user utterance (corrections, decisions, feedback -- the most important part)
  - assistant text (conclusions/judgements, truncated when long)
  - tool use as a one-line summary only (Edit/Write target file, first line of a Bash command)
Tool result bodies are dropped -- that is where most of the volume lives (several MB to tens of MB).

Usage:
  python3 compact_transcript.py <transcript.jsonl>        # write to stdout
  python3 compact_transcript.py <transcript.jsonl> -o out.md
  python3 compact_transcript.py <transcript.jsonl> --require-attributed-user  # strict, for retrospection
"""
import argparse
import json
import os
import sys
from collections import namedtuple

ASSIST_MAX = 600  # truncation length for a single assistant text block


def _text_blocks(content):
    """Extract a list of (kind, text) from content (str|list)."""
    out = []
    if isinstance(content, str):
        out.append(("text", content))
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                out.append(("text", b.get("text", "")))
            elif t == "tool_use":
                name = b.get("name", "")
                inp = b.get("input", {}) or {}
                if name in ("Edit", "Write", "MultiEdit", "Read", "NotebookEdit"):
                    out.append(("tool", f"{name}({inp.get('file_path', '')})"))
                elif name == "Bash":
                    cmd = (inp.get("command", "") or "").splitlines()
                    out.append(("tool", f"Bash: {cmd[0][:80] if cmd else ''}"))
                else:
                    out.append(("tool", name))
    return out


# Origins we accept as "a human typed this". Anything else was inserted by a tool or the system.
HUMAN_PROMPT_SOURCES = {"typed", "queued", "suggestion_accepted"}

# Fallback for old transcripts that carry no origin signal. An injected turn **starts** with one
# of these. We only look at the start, so a normal utterance that merely *mentions* a marker survives.
#
# WARNING: these are **family prefixes**, not individual tags. The first version listed tags one by
# one and missed `<command-message>` (6 occurrences in the measured corpus). New variants of the same
# family keep appearing -- command-name/message/args, local-command-stdout/stderr/caveat,
# bash-input/stdout/stderr. Matching the family covers the new variants too.
# A human-typed message practically never **starts** with one of these tags.
#
# NOTE: these entries are **matchers against historical transcript data**, not output. Do not reword
# them -- the plain-text entry below is the literal prefix Claude injects for skill bodies.
_INJECTED_HEADS = (
    "<command-", "<local-command-", "<bash-",
    "<task-notification>", "<system-reminder>",
    "Base directory for this skill",   # skill-body injection — starts with plain text, not a tag
)


Turn = namedtuple("Turn", "role blocks provenance evidence")


def _claude_user_provenance(d, text):
    """Did a **human type** this user turn?

    `role: "user"` in a Claude transcript is not only human input. Tool notifications
    (`<task-notification>`), slash-command expansions (`<command-name>`, `<local-command-stdout>`),
    system reminders, and **skill bodies** all land in the same slot.

    As retrospection material that is fatal -- if a skill body enters as "what the user said", the
    retrospective extracts **the harness's own rules** as a new lesson and files it as a promotion
    candidate. It is already written in our voice, so it looks more plausible than a real lesson.
    Measured: 6 of 9 USER blocks in one transcript were injections.

    ## Why positive selection alone is not enough

    Recent transcripts carry `origin: {kind: "human", promptSource: "typed"}`. Selecting on that is
    clean. But **40 of this project's 46 files do not have the field at all** -- they predate it.
    Filtering strictly yields **zero** user utterances in those 40, which is indistinguishable from
    "there was nothing to reflect on". That is a failure mode this repo keeps hitting.

    So we judge **per record, not per file** -- trust origin when it is attached, and fall back to
    markers when it is not. The caller announces that the fallback was used (see compact).
    """
    # WARNING: promptSource lives at the **record top level**, not inside origin (measured:
    # origin.promptSource was None in all 2616 records -- reading it there is a dead condition).
    # It is also the most accurate signal: 40 sdk and 22 system records arrive without origin.kind,
    # so looking only at origin drops them into the marker fallback, and since they are plain text
    # they pass as human input. Automation-injected prompts would become retrospection material.
    src = d.get("promptSource")
    if src is not None:
        return ("attributed" if src in HUMAN_PROMPT_SOURCES else "nonhuman",
                "promptSource", False)
    origin = d.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return ("attributed" if origin["kind"] == "human" else "nonhuman",
                "origin", False)
    if d.get("isMeta"):
        return "nonhuman", "isMeta", False
    # `startswith`, not `in`. An injected turn **starts** with a marker. With `in` we would also
    # kill a normal utterance that talks about one ("why does the compactor filter <task-notification>?").
    head = text.lstrip()
    if head.startswith(_INJECTED_HEADS):
        return "nonhuman", "marker", True
    return "unattributed", "marker", True


def _claude_msg(d):
    """Claude Code record -> Turn, or None.

    provenance is one of attributed/unattributed/nonhuman, and only on user records. We do not throw
    the classification away at this boundary so that strict retrospection can select per record
    segment rather than per whole file.
    """
    m = d.get("message")
    if not isinstance(m, dict):
        return None
    blocks = _text_blocks(m.get("content"))
    if m.get("role") != "user":
        role = m.get("role")
        return Turn(role, blocks, None, None) if role == "assistant" else None
    user_texts = [t for k, t in blocks if k == "text" and t.strip()]
    # tool_result records are also role=user in Claude JSONL. They carry no retrospection text and
    # are dropped by the renderer below, so they are not subject to a provenance verdict. Counting
    # them as a fallback would make strict retrospection reject almost every tool-using session.
    if not user_texts:
        return None
    text = " ".join(user_texts)
    provenance, evidence, _fallback = _claude_user_provenance(d, text)
    return Turn("user", blocks, provenance, evidence)


def _codex_user_message(d):
    """The **real user utterance** in a Codex rollout -- `message` inside `event_msg.user_message`.

    WARNING: never read `role: "user"` on a `response_item` as a user utterance. Codex puts injected
    context there with `role: "user"` too -- `<user_action>` wrappers, environment info, the
    project's AGENTS.md body. Measured across 8 sessions, **8 of those 17 items were injections**.

    As retrospection material that is fatal. If the whole of AGENTS.md enters as "what the user
    said", the retrospective extracts it as a new lesson and files it as a memory promotion
    candidate -- the project's existing rules disguise themselves as user feedback and self-replicate.

    Codex distinguishes the two for us. Real input only ever arrives via `event_msg.user_message`.
    """
    if d.get("type") != "event_msg":
        return None
    p = d.get("payload") or {}
    if p.get("type") != "user_message":
        return None
    text = p.get("message")
    if not isinstance(text, str) or not text.strip():
        return None
    return Turn("user", [("text", text)], "attributed", "codex-channel")


def _codex_msg(d):
    """Codex rollout .jsonl: {"type":"response_item","payload":{"type":"message",
    "role","content":[{"type":"input_text"|"output_text","text"}]}} -> (role, blocks).
    tool(function_call) entries are omitted in v1 -- only user/assistant text is extracted."""
    if d.get("type") != "response_item":
        return None
    p = d.get("payload") or {}
    if p.get("type") != "message":
        return None
    # Only assistant. role="user" mixes in injections, so _codex_user_message handles it separately,
    # and role="developer" is a system instruction, not retrospection material.
    if p.get("role") != "assistant":
        return None
    blocks = [
        ("text", b.get("text", ""))
        for b in (p.get("content") or [])
        if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text")
    ]
    return Turn("assistant", blocks, None, None)


def iter_turns(path, stats=None):
    """Parse JSONL into a policy-agnostic stream of Turns.

    nonhuman turns are not dropped either. Whether to hide such a turn or to revoke the trusted
    segment is the consuming policy's responsibility. ``stats`` reports the total line count and
    whether the marker fallback was used back to the caller.
    """
    if stats is None:
        stats = {}
    stats.update(lines=0, used_fallback=False)
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            stats["lines"] += 1
            try:
                d = json.loads(ln)
            except Exception:
                continue
            turn = _claude_msg(d)
            if turn is None:
                turn = _codex_user_message(d)
            if turn is None:
                turn = _codex_msg(d)
            if turn is None:
                continue
            if turn.evidence == "marker":
                stats["used_fallback"] = True
            yield turn


def select_recovery(turns, stats=None):
    """Best-effort policy for the ordinary CLI: drop injections only, keep unattributed user turns."""
    for turn in turns:
        if turn.provenance != "nonhuman":
            yield turn


def select_attributed(turns, stats=None):
    """Fail-closed policy for retrospection: keep only segments that start at a confirmed user turn.

    Plain notification/meta nonhuman turns are transparent, but an explicitly attributed automation
    turn and an unattributed user turn both make the assistant replies that follow untrustworthy,
    so they revoke segment trust.
    """
    if stats is None:
        stats = {}
    stats.update(attributed_users=0, unattributed_users=0, nonhuman_users=0)
    trusted_segment = False
    for turn in turns:
        if turn.role == "user":
            if turn.provenance == "attributed":
                trusted_segment = True
                stats["attributed_users"] += 1
                yield turn
            elif turn.provenance == "unattributed":
                stats["unattributed_users"] += 1
                trusted_segment = False
            elif turn.provenance == "nonhuman":
                stats["nonhuman_users"] += 1
                if turn.evidence in ("promptSource", "origin"):
                    trusted_segment = False
            continue
        if turn.role == "assistant" and trusted_segment:
            yield turn


def render(turns):
    """Render the selected Turn stream into the compact markdown format."""
    md = []
    for turn in turns:
        role, blocks = turn.role, turn.blocks
        if role == "user":
            for kind, txt in blocks:
                if kind == "text" and txt.strip():
                    md.append(f"\n### 👤 USER\n{txt.strip()}")
        elif role == "assistant":
            texts = [t for k, t in blocks if k == "text" and t.strip()]
            tools = [t for k, t in blocks if k == "tool"]
            if texts:
                joined = "\n".join(texts).strip()
                if len(joined) > ASSIST_MAX:
                    joined = joined[:ASSIST_MAX] + " …(truncated)"
                md.append(f"\n**🤖 ASSISTANT:** {joined}")
            if tools:
                md.append(f"  ↳ tools: {', '.join(tools[:8])}" + (" …" if len(tools) > 8 else ""))
    return "\n".join(md)


def compact(path, require_attributed_user=False):
    """Compact a transcript.

    `require_attributed_user=True` is the fail-closed mode used for memory retrospection. It drops
    only unattributed user turns and the assistant segments that follow them, keeping segments that
    start at a positively attributed user turn. If there is no positively attributed user turn at
    all, the whole output is emptied. The default, False, is the compatible mode for the general CLI.
    """
    parse_stats = {}
    policy_stats = {}
    turns = iter_turns(path, parse_stats)
    if require_attributed_user:
        selected = select_attributed(turns, policy_stats)
    else:
        selected = select_recovery(turns, policy_stats)
    out = render(selected)
    if parse_stats["used_fallback"] and not require_attributed_user:
        # Do not degrade silently. The marker fallback is weaker than origin-based selection, so
        # whoever reflects on this compaction must know it "may be less filtered".
        sys.stderr.write(
            "[compact] some old records have no origin, so filtering fell back to markers "
            "— injections may remain\n")
    if require_attributed_user and policy_stats["attributed_users"] == 0:
        sys.stderr.write("[compact] retrospection refused: no user turn with a confirmed origin\n")
        return "", parse_stats["lines"]
    if require_attributed_user:
        sys.stderr.write(
            "[compact] strict user turns: "
            f"attributed {policy_stats['attributed_users']}, "
            f"dropped as unattributed {policy_stats['unattributed_users']}, "
            f"dropped as injected {policy_stats['nonhuman_users']}\n")
    return out, parse_stats["lines"]


def main():
    parser = argparse.ArgumentParser(description="Claude/Codex transcript compactor")
    parser.add_argument("transcript")
    parser.add_argument("-o", "--output")
    parser.add_argument("--require-attributed-user", action="store_true")
    # Existing runnability contract: a no-argument call avoids exit 2, which also means "block"
    # in the hook contract. Unknown options are handled fail-closed by parse_args below (exit 2).
    if len(sys.argv) == 1:
        parser.print_usage(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()
    out, n = compact(args.transcript, require_attributed_user=args.require_attributed_user)
    if args.require_attributed_user and not out.strip():
        if args.output and os.path.exists(args.output):
            os.remove(args.output)
        sys.exit(3)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(out)
        sys.stderr.write(
            f"[compact] {n} lines → {args.output} ({len(out)} chars, ~{len(out)//4} tokens)\n")
    else:
        print(out)
        sys.stderr.write(f"[compact] {n} lines → {len(out)} chars (~{len(out)//4} tokens)\n")


if __name__ == "__main__":
    main()
