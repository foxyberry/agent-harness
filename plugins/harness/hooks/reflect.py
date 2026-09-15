#!/usr/bin/env python3
"""
Self-improving retrospection job.

Compacts the session transcript (.jsonl) -> analyses it with an LLM -> stores two kinds of "drafts":
  - lesson memories  -> `.claude/memory/_pending/`
  - decision ADRs    -> `.claude/memory/_pending/decisions/` (proposed_chain/supersedes are
    proposals only)
(A human reviews and promotes them in the next session via `/memory-update`. Chain assignment is
confirmed by the human.)

The backend is pluggable -- select it with the REFLECT_BACKEND environment variable (default claude):
  - claude   : local `claude -p` (uses the subscription, no key needed, best quality)  <- default
  - deepseek : DeepSeek API (needs DEEPSEEK_API_KEY, cheap/fast)
  - ollama   : local ollama (REFLECT_OLLAMA_MODEL, offline/free, lower quality)

Usage:
  python3 reflect.py --transcript <session.jsonl> [--backend claude|deepseek|ollama]

Note: the claude backend sets REFLECT_JOB=1 on the child process to prevent the recursion where a
nested `claude -p` fires the hook again. The hook (pr-merge-reflect.py) no-ops when it sees that
value.

This script has to be co-located with the hook (pr-merge-reflect.py) in the same directory
(compact_transcript.py too). In a plugin deployment the script location and the project location are
separate, so the hook finds this file via dirname(__file__).
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_transcript import compact  # noqa: E402

# Sentinel returned by the index helpers when a project has no data yet. Both helpers return the
# **same** string so the prompt reads consistently.
NONE_YET = "(none yet)"

# Section headings assembled into the prompt by main(). PROMPT quotes these same phrases verbatim
# when it tells the model to consult them, so the instruction and the section it points at must stay
# in sync -- test_rejected_drafts pins that they do.
REJECTED_SECTION = "already rejected drafts"
DECISIONS_SECTION = "existing decision chain index"


# Shared between generators -- the ADR draft contract (gate + frontmatter fields + body sections).
# Both generators, reflect (session retrospection) and mine (git back-mining), compose this. They go
# through the same _split_drafts -> the same _pending/decisions routing -> the same /memory-update
# promotion path, so a field mismatch misroutes drafts. The contract is defined in this one place
# only (to prevent issue #19 recurring).
ADR_DRAFT_CONTRACT = """\
Only **decisions** where "why it was done that way" matters. They must pass the gate:
- It is an ADR only if it has both the **Alternatives** not taken and the **Consequence**. Without those it is not an ADR -> turn it into a lesson memory or drop it.
- Criteria: there was a rejected alternative / the direction changed / the decision is expensive to reverse. **0-3 of them, each covering exactly one decision (keep them small)**.
- **Do not finalise the chain assignment, only propose it** -- consult the "existing decision chain index" below; use that chain slug if this continues an existing axis, or `new:<name>` for a new axis. Lower the confidence when you are unsure.
- Wrap each draft in a single **four-backtick** block (because ``` code quotes may appear inside):

````
---
name: <kebab-case-slug>
description: <one-line summary — used in the INDEX and search summaries. Always fill this in>
type: decision
proposed_chain: <an existing chain slug or new:name>
proposed_supersedes: [<existing id>, ...]   # ids of earlier decisions this one replaces. [] if none
confidence: high | medium | low             # how confident the chain/supersedes proposal is
keywords: [<search term>, ...]              # the search surface — always fill this in
---
## Context
## Decision
## Alternatives
## Consequence
## Evidence
````"""


PROMPT = ("""You are a "self-improving retrospection system". Below is the compacted conversation
transcript of one work session. Extract **two kinds** of drafts from it: (A) lessons worth
persisting (memory), and (B) important decisions (ADR).

## (A) Lesson memories
- Prioritise the corrections, course-changes and decisions the user gave (especially "don't do X",
  "do it this way", changes of approach).
- Exclude one-off facts specific to this session (a particular PR number, a particular file path).
  Only patterns that generalise. When in doubt, leave it out.
- **Read the "already rejected drafts" list below first.** If it says the same thing, do not create
  it again -- a human has already looked at it and decided not to keep it. Different wording for the
  same lesson still counts as the same thing.
  WARNING: it is not a ban list. If **the same thing has recurred since and now has value**, you may
  raise it again -- but then write **what changed** in the draft (how many more times it recurred,
  what it cost).
- 0-5 of them. Wrap each draft in a single **four-backtick** block (because ``` code quotes may
  appear inside):

````
---
name: <kebab-case-slug>
description: <one-line summary>
type: feedback | project | user | reference
---
<the core content. For feedback/project, include **Why:** and **How to apply:** lines>
````

## (B) Decision ADRs
""" + ADR_DRAFT_CONTRACT + """

- Write the draft prose (description, body, section text) in **English**, even when the source
  material is in another language. Keep quoted evidence, code, file paths, commands and identifiers
  in their original language and exact wording -- quote them, do not translate them.

Output only the (A) and (B) draft code blocks, with no commentary. If there is nothing to extract,
output nothing at all.
""")


def _project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _rejected_index(project_dir):
    """The list of drafts a human already rejected -- fed into the prompt so the LLM does not
    recreate the same ones.

    ## Why this is needed

    Rejecting a draft deletes the file. **The fact that it was rejected is recorded nowhere.** The
    next session reads the same transcript, extracts the same lesson, and creates the same draft
    again. The human throws it away again. The bigger the backlog, the more this cost repeats
    (issue #109).

    ## Why not a regex or a similarity score

    "Is this the same lesson" cannot be settled by string comparison -- the same point written in
    different words is missed. But **an LLM is already making that judgement.** Showing it the
    rejection list works exactly like `_decisions_index` putting existing ADRs in the prompt to get
    chain proposals: it recognises them. No separate machinery is needed.

    ## Why a prompt hint rather than a hard filter

    Blocking something **forever** because it was rejected once would be its own bug -- a lesson
    dropped in July as "too trivial" gains value if it recurs three more times by September. Putting
    it in the prompt lets the LLM weigh the circumstances and raise it again. That is why no expiry
    rule is needed.

    Returns `(none yet)` when the file is absent. Like `_decisions_index`, this **only reads**.
    """
    path = os.path.join(project_dir, ".claude/memory/_rejected.md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return NONE_YET
    # WARNING: strip comment blocks **first**. The template puts its example entries inside
    # `<!-- ... -->`, and a line-oriented pass sees those examples start with `- ` and **takes them
    # for real rejection records.** Every project that copied the template would inject rejections
    # that never happened into the prompt, silently blocking similar lessons.
    # (Same reason `_decisions_index` filters out README and EXAMPLE files.)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    # An entry is a line starting with `- `. Everything else (titles, prose) is ignored.
    # NOTE: this is a **language-agnostic** parse — existing Korean `_rejected.md` ledgers keep
    # working unchanged even though newly generated prompt text is English.
    rows = [l.rstrip() for l in text.splitlines() if l.startswith("- ")]
    if not rows:
        return NONE_YET
    # The file is append-only, so **the tail is the newest**. When it overflows, drop the old head --
    # the more recent a rejection is, the likelier it is to be generated again.
    cap = 50
    truncated = len(rows) > cap
    out = "\n".join(rows[-cap:])
    if truncated:
        out += f"\n(… {len(rows) - cap} older entries omitted)"
    return out


def _decisions_index(project_dir):
    """A summary index of the existing decision ADRs (chain, id, keywords) -- fed into the prompt so
    the LLM can propose proposed_chain/proposed_supersedes. Returns the "none yet" sentinel when
    absent.
    This **only reads** project data (.claude/memory/decisions/) -- no project-specific hardcoding
    goes into the engine (the harness's engine/data separation)."""
    ddir = os.path.join(project_dir, ".claude/memory/decisions")
    if not os.path.isdir(ddir):
        return NONE_YET
    rows = []  # (mtime, block)
    for fn in os.listdir(ddir):
        # Exclude the README (the schema document) and example ADRs (EXAMPLE) from automation input
        # -- this stops a new project that copied the template verbatim from having its examples
        # injected into the LLM as "real existing chains" and proposed as supersedes candidates.
        if not fn.endswith(".md") or fn == "README.md" or "EXAMPLE" in fn.upper():
            continue
        fp = os.path.join(ddir, fn)
        try:
            head = open(fp, encoding="utf-8").read(2000)
            mt = os.path.getmtime(fp)
        except OSError:
            continue
        parts = head.split("---", 2)
        block = parts[1] if len(parts) >= 3 else head
        if not _is_decision(block):  # same normalisation as routing (quotes/comments/case)
            continue
        rows.append((mt, block))
    if not rows:
        return NONE_YET
    # Sort by mtime (newest first) before capping, not by file name -- names are descriptive, so
    # sorting by them reflects neither time nor relevance, and as decisions pile up the active
    # (recent) chains could be pushed past the cap and silently disappear. Recent ones win.
    rows.sort(key=lambda r: r[0], reverse=True)
    cap = 50
    truncated = len(rows) > cap
    blocks = [b for _mt, b in rows[:cap]]
    # One-way supersedes model: superseded_by is not stored, it is computed here at lookup time.
    # An id that another decision claims via supersedes is marked "superseded" (so it is not
    # mistaken for an active candidate).
    superseded = set()
    for b in blocks:
        superseded |= set(_fm_list(b, "supersedes"))
    lines = []
    for b in blocks:
        _id = _fm(b, "id") or "?"
        status = _fm(b, "status").split("#", 1)[0].strip().strip("\"'").lower()
        if _id in superseded:
            mark = " (superseded)"
        elif status == "rejected":
            mark = " (rejected)"  # a rejected decision -- not a continuation or supersedes candidate
        else:
            mark = ""
        lines.append(
            f"- chain={_fm(b, 'chain') or '?'} | id={_id}{mark} | "
            f"{_fm(b, 'description') or _fm(b, 'name')} | keywords={_fm(b, 'keywords')}"
        )
    if truncated:
        lines.append(f"- … (showing only the {cap} most recent of {len(rows)} decisions)")
    return "\n".join(lines)


def _fm(block, key):
    """A single-line frontmatter value ('' when absent)."""
    m = re.search(rf"^{key}:\s*(.+)$", block, re.M)
    return m.group(1).strip() if m else ""


def _fm_list(block, key):
    """An inline frontmatter list (`key: [a, b]`) -> [a, b]. [] when absent."""
    m = re.search(rf"^{key}:\s*\[(.*?)\]", block, re.M)
    if not m:
        return []
    return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()]


def _is_decision(block):
    """Is the frontmatter type `decision`? Lenient about quote/inline-comment/case variants --
    otherwise a valid variant such as `type: "decision"` is misrouted to _pending/ and consumers
    never see it."""
    m = re.search(r"^type:\s*(.+)$", block, re.M)
    if not m:
        return False
    val = m.group(1).split("#", 1)[0].strip().strip("\"'").lower()
    return val == "decision"


# ---------- Backends ----------

def _backend_claude(prompt):
    env = {**os.environ, "REFLECT_JOB": "1"}  # recursion guard: makes the nested claude's hook no-op
    r = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True, timeout=300, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"claude -p failed: {r.stderr[:300]}")
    return r.stdout


def _backend_deepseek(prompt):
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    model = os.environ.get("REFLECT_DEEPSEEK_MODEL", "deepseek-chat")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def _backend_ollama(prompt):
    model = os.environ.get("REFLECT_OLLAMA_MODEL", "qwen2.5:14b")
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=payload, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["response"]


BACKENDS = {
    "claude": _backend_claude,
    "deepseek": _backend_deepseek,
    "ollama": _backend_ollama,
}


# ---------- Output parsing -> draft files ----------

def _fenced_blocks(text):
    """The bodies of the backtick blocks. **A closing fence must be at least as long as the opening
    one** and must carry no language tag.

    Those two conditions solve the nested-quote problem -- if the outer fence opens with ````, an
    inner ``` is too short to close it. Nothing is counted or guessed.
    """
    fence = re.compile(r"^(`{3,})\s*([A-Za-z0-9_+-]*)\s*$")
    blocks, buf, opener = [], None, 0
    for line in text.splitlines():
        m = fence.match(line.strip())
        if m and buf is None:
            buf, opener = [], len(m.group(1))
            continue
        if m and buf is not None and not m.group(2) and len(m.group(1)) >= opener:
            blocks.append("\n".join(buf))
            buf = None
            continue
        if buf is not None:
            buf.append(line)
    if buf is not None:                      # unclosed = the output was truncated
        blocks.append("\n".join(buf))
    return blocks


def _split_drafts(text):
    """Extract the blocks that carry frontmatter from the LLM output.

    ## Why four backticks

    Quoting code inside a draft is the norm, not the exception -- the ADR contract requires an
    `Evidence` section. But if the outer fence is ``` and the inner quote is ``` too, **there is no
    way to tell them apart.** Counting by the presence of a tag does not work either: untagged ```
    quotes are common and are character-for-character identical to a closing fence. Guessing
    truncates the draft, and a truncated draft is stored in `_pending/` looking perfectly fine, so a
    human reviews it for promotion.

    So **the prompt demands four backticks.** We own both the prompt and the parser, so we can remove
    the ambiguity -- instead of trying to parse better, we make the thing being parsed unambiguous.

    Three-backtick blocks are a **compatibility fallback** (old output, instruction drift). That path
    still carries the original ambiguity, so if there is even one four-backtick block we use only
    those.
    """
    blocks = _fenced_blocks(text)
    kept = [b.strip() for b in blocks
            if "name:" in b and re.search(r"^type:", b, re.M)]
    # If the final block survived unclosed, the output was truncated. Dropping it wholesale would be
    # indistinguishable from "there was nothing to extract", so we keep it but announce the truncation.
    if kept and not text.rstrip().endswith("`"):
        sys.stderr.write(
            "[reflect] ⚠️ final block is unclosed — output looks truncated. Keeping it as-is\n")
    return kept


def _slug(block):
    m = re.search(r"^name:\s*(.+)$", block, re.M)
    s = (m.group(1).strip() if m else "draft")
    return re.sub(r"[^a-z0-9-]", "-", s.lower())[:60] or "draft"


def main():
    args = sys.argv[1:]

    def _flag_value(flag):
        """The value after --flag. None when the flag is absent or has no value (avoids IndexError)."""
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return None

    transcript = _flag_value("--transcript")
    if transcript is None:
        sys.exit("usage: reflect.py --transcript <session.jsonl> [--backend claude|deepseek|ollama]")
    backend = _flag_value("--backend") or os.environ.get("REFLECT_BACKEND", "claude")
    if backend not in BACKENDS:
        sys.exit(f"unknown backend: {backend}")
    if not os.path.exists(transcript):
        sys.exit(f"transcript not found: {transcript}")

    # Memory drafts are built only from user turns with a confirmed origin. Recovery (fw/history) may
    # read old logs best-effort, but for rule-promotion candidates trust beats recall (issue #121).
    body, n = compact(transcript, require_attributed_user=True)
    if not body.strip():
        sys.exit(0)  # empty session -> stay quiet

    project_dir = _project_dir()
    prompt = (
        PROMPT
        + f"\n=== {REJECTED_SECTION} (do not create the same thing again) ===\n"
        + _rejected_index(project_dir)
        + "\n\n=== " + DECISIONS_SECTION + " (reference for proposed_chain/proposed_supersedes) ===\n"
        + _decisions_index(project_dir)
        + "\n\n=== compacted transcript ===\n"
        + body
    )
    text = BACKENDS[backend](prompt)
    drafts = _split_drafts(text)
    if not drafts:
        sys.stderr.write("[reflect] no drafts\n")
        return

    pending = os.path.join(project_dir, ".claude/memory/_pending")
    written = []
    for d in drafts:
        slug = _slug(d)
        # Decision (ADR) drafts route to _pending/decisions/, lesson memories to _pending/.
        target = os.path.join(pending, "decisions") if _is_decision(d) else pending
        os.makedirs(target, exist_ok=True)
        path = os.path.join(target, f"{slug}.md")
        # If a draft with the same slug is already pending, keep it and add a suffix instead of
        # overwriting -- this prevents losing an unreviewed draft. (/memory-update merges duplicates
        # during review, so accumulating them is safe.)
        i = 2
        while os.path.exists(path):
            path = os.path.join(target, f"{slug}-{i}.md")
            i += 1
        open(path, "w", encoding="utf-8").write(d + "\n")
        written.append(os.path.relpath(path, pending))
    sys.stderr.write(
        f"[reflect] backend={backend} transcript {n} lines → {len(written)} draft(s): "
        f"{', '.join(written)}\n"
    )


if __name__ == "__main__":
    main()
