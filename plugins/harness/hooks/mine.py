#!/usr/bin/env python3
"""
Decision back-mining.

Analyses a slice of git history (commit message bodies) with an LLM -> retroactively extracts
decisions that were already made as ADR drafts -> drops them onto the **same promotion path** as
reflect (`_pending/decisions/` -> `/memory-update` 1.6).

Reuses reflect.py's draft contract (`ADR_DRAFT_CONTRACT`), backends, parsing and routing -- this is
just **another draft generator** whose input is a "git slice" instead of a "session transcript".
(Design: docs/decision-mining.md, issue #21)

Usage:
  python3 mine.py <rev-range> [--backend claude|deepseek|ollama]
  e.g. python3 mine.py origin/main~20..origin/main
       python3 mine.py <merge_commit>^..<merge_commit>   # a single-PR slice

Limits (nailed down by design):
  - If the commit does not say "why", no draft is produced (inventing a missing rationale = fake
    history).
  - chain and supersedes stay proposed_* only -- a human confirms them via /memory-update
    (positive-only inheritance).
  - The Codex hooks are deferred, so this script ships only in the Claude adapter (same as
    reflect.py).
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reflect import (  # noqa: E402
    BACKENDS,
    ADR_DRAFT_CONTRACT,
    DECISIONS_SECTION,
    _decisions_index,
    _split_drafts,
    _slug,
    _is_decision,
    _project_dir,
)

MINE_PROMPT = ("""You are a "decision archaeologist". Below is a slice of one repository's git
history (a collection of commit messages). Retroactively recover the **important decisions (ADRs)
that were already made** and write them up as drafts.

- Extract one **only when the commit message actually states the "why" (the rationale)**. If it does
  not, **do not invent** a reason -- that is fake history. Silently skip commits with no signal.
- "What changed" (a list of features or refactors) is not an ADR. Only things where **"why it was
  done that way" is visible together with its grounds**: a rejected alternative, a change of
  direction, a choice that is expensive to reverse.
- In the Evidence section, record the commit hashes (short form) the draft is grounded in.

""" + ADR_DRAFT_CONTRACT + """

- Write the draft prose (description, body, section text) in **English**, even when the source
  material is in another language. Keep quoted evidence, code, file paths, commands and identifiers
  in their original language and exact wording -- quote them, do not translate them.

Output only the draft code blocks, with no commentary. If there is nothing to extract, output
nothing at all.
""")


def git_slice(root, rev_range):
    """Compact the messages (subject + body) of the commits in rev_range into mining input text.

    The diff is not included -- the "why" lives in the message (if anywhere), not in the code.
    Bounding the input by rev_range **slices** the firehose (never the whole history at once).
    Returns: (text, commit count)."""
    fmt = "%H%x1f%ad%x1f%s%x1f%b%x1e"  # x1f = field separator, x1e = record separator
    r = subprocess.run(
        ["git", "-C", root, "log", "--no-merges", "--date=short", f"--format={fmt}", rev_range],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        sys.exit(f"git log failed: {r.stderr.strip()[:300]}")
    records = [rec for rec in r.stdout.split("\x1e") if rec.strip()]
    lines = []
    for rec in records:
        parts = rec.strip().split("\x1f")
        if len(parts) < 4:
            continue
        h, ad, subj, body = parts[0][:9], parts[1], parts[2], parts[3].strip()
        lines.append(f"### {h} ({ad}) {subj}")
        if body:
            lines.append(body)
    return "\n".join(lines), len(records)


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        sys.exit("usage: mine.py <rev-range> [--backend claude|deepseek|ollama]")
    rev_range = args[0]
    backend = "claude"
    if "--backend" in args:
        i = args.index("--backend")
        if i + 1 < len(args):
            backend = args[i + 1]
    if backend not in BACKENDS:
        sys.exit(f"unknown backend: {backend}")

    root = _project_dir()
    body, n = git_slice(root, rev_range)
    if not body.strip():
        sys.exit(f"empty slice — '{rev_range}' has no commits (merges excluded)")

    prompt = (
        MINE_PROMPT
        + "\n=== " + DECISIONS_SECTION + " (reference for proposed_chain/proposed_supersedes) ===\n"
        + _decisions_index(root)
        + "\n\n=== git history slice ===\n"
        + body
    )
    text = BACKENDS[backend](prompt)
    drafts = _split_drafts(text)

    pending = os.path.join(root, ".claude/memory/_pending/decisions")
    written = []
    for d in drafts:
        if not _is_decision(d):
            continue  # mining produces ADRs only -- non-decision drafts are discarded
        os.makedirs(pending, exist_ok=True)
        slug = _slug(d)
        path = os.path.join(pending, f"{slug}.md")
        # If the same slug is already pending, keep it and add a suffix rather than overwriting
        # (same as reflect -- /memory-update merges them).
        i = 2
        while os.path.exists(path):
            path = os.path.join(pending, f"{slug}-{i}.md")
            i += 1
        open(path, "w", encoding="utf-8").write(d + "\n")
        written.append(os.path.basename(path))
    sys.stderr.write(
        f"[mine] backend={backend} {rev_range} {n} commit(s) → {len(written)} ADR draft(s)"
        f"{': ' + ', '.join(written) if written else ' (normal for a slice that records no why)'}\n"
    )


if __name__ == "__main__":
    main()
