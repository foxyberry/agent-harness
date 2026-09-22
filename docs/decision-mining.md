# Decision mining — implementation and design

**Status:** a limited commit-message mining CLI is implemented in
[`core/hooks/mine.py`](../core/hooks/mine.py) and shipped in the **Claude adapter**. The broader
combination of PR discussions, issues, and session logs remains a design direction, not an
implemented end-to-end feature. The original exploration is in
[issue #15](https://github.com/foxyberry/agent-harness/issues/15); the implementation followed in
[issue #21](https://github.com/foxyberry/agent-harness/issues/21).

## Purpose

Retrospectives record decisions **as work happens** in `decisions/` ADRs: forward capture.
Decision mining recovers decisions **already made** from historical evidence: backward mining.
Both feed the same decision history, so mining can seed older decisions and retrospectives can
continue the record from there.

```text
Past: backward mining                    Ongoing work: forward capture
commit messages → ADR drafts → decisions/ ← retrospective drafts
                                 ↑        ← session candidates (0.14.0)
                       human review and promotion

Planned additional mining inputs: PR discussions, issues, and session logs
```

A long development history is too large to put directly into an agent's context. A larger viewer
alone does not solve that problem: the useful output is a compact record of **why** choices were
made. Commits and PRs often describe what changed, but contain little rationale. Statistics and
visualizations cannot recover reasons that were never recorded.

## What is implemented

`mine.py` accepts an explicit Git revision range, reads commit subjects and bodies with
`git log --no-merges`, and sends that slice to an LLM. It does **not** fetch PR or issue text,
read session logs, or include diffs. The prompt asks for significant decisions only when the
messages actually contain rationale, and asks for the supporting commit hash in Evidence.

It reuses `reflect.py`'s backend implementations, `ADR_DRAFT_CONTRACT`, existing-decision index,
draft parsing, and decision classification. Only decision drafts are written, under
`.claude/memory/_pending/decisions/`. An existing slug is preserved; a new draft gets a numeric
suffix. An empty Git slice exits without invoking the backend. A nonempty slice can legitimately
produce no ADR drafts.

### Run the CLI

From the **target repository root**, use the installed Claude plugin's bundled script. Replace
`<installed-plugin-root>` with the actual installation path, and choose a small revision range
that exists in that repository:

```bash
python3 "<installed-plugin-root>/hooks/mine.py" origin/main~20..origin/main --backend claude
```

The target directory is `CLAUDE_PROJECT_DIR` when set, otherwise the process working directory.
If that variable is already set, verify it points to the intended target repository.

To mine one squash-merge commit, replace `<squash-commit>` below with its hash:

```bash
python3 "<installed-plugin-root>/hooks/mine.py" '<squash-commit>^..<squash-commit>' --backend claude
```

Because the reader uses `--no-merges`, a range containing only a true merge commit is empty.
Choose a range containing the relevant non-merge commits instead. The input is bounded by your
chosen revision range; there is no separate input-size budget, so avoid sending the entire
history at once.

Supported `--backend` values are `claude`, `deepseek`, and `ollama`. The mining CLI defaults to
`claude`; unlike the retrospective CLI, it does **not** use `REFLECT_BACKEND` to choose that
default. Running `mine.py` explicitly invokes the selected backend and does not require
`HARNESS_AUTO_REFLECT=1`, which gates automatic hook jobs.

Review resulting drafts with `/memory-update`. This is a script, **not a slash-command skill**.
`build.sh` copies it and its LLM helpers into `plugins/harness/hooks/`; the Codex hook bundle
omits them. Both tools have `/memory-update` and can review the resulting shared-project drafts.

The output remains a proposal. The prompt forbids invented rationale, but the code does not
independently prove every LLM claim: validate it against the cited commits during review.

## Research context and positioning

The following summarizes the **historical exploration in issue #15**, not a fresh assessment of
current third-party capabilities. Its comparison axis was (a) extracting decision rationale
from history, versus (b) showing change statistics or explaining a current code snapshot.

| Category considered in #15 | Examples examined | Distinction used in that exploration |
|---|---|---|
| Evolution statistics and visualization | CodeScene, code-maat, git-of-theseus, Hercules | Primarily examined for where and how much code changed |
| Repository-to-explanation tools | DeepWiki, Cody, Continue `@codebase`, Aider | Examined as current-code explanation rather than a decision history |
| Adjacent commercial approach | Unblocked | Considered for combining PRs with Slack/Jira context |
| Adjacent research | CoMRAT (MSR 2025) | Considered for decision/rationale classification from commit messages |
| Adjacent emerging approach | repowise | Considered for decision archaeology using multiple sources |

The investigation did not establish an empty market or justify claiming a unique product.
It pointed to an evidence limitation: **Git contains rationale only when someone wrote it down**.
An LLM must not fill gaps with invented reasons.

The proposed position for this harness is therefore to connect **Git, session logs, and
retrospectives into a reviewed decision history**. The existing `fw` log readers and `reflect`
draft pipeline make that a plausible extension, but their existence does not mean the
multi-source mining pipeline is already connected. Reassess external product comparisons before
using them as current positioning claims.

## Candidate sources for future mining

These are design candidates. Only commit messages are currently consumed by `mine.py`.

| Source | Potential signal | Expected strength | Limitation |
|---|---|---|---|
| PR descriptions and review discussions | Why an option was chosen; rejected alternatives | Strong | Missing from histories built through direct pushes |
| Issue descriptions and comments | Problem definitions, alternatives, `Closes #` links | Strong | Unavailable when a team does not use issues |
| Commit message bodies | Rationale, alternatives, reversals | Medium | One-line summaries often contain little reasoning |
| Session logs used by `fw` | Deliberation and reasons for rejecting options | Strong | Local to the machine where the logs remain |
| Commit/file churn | Areas under repeated decision pressure | Weak | Helps select where to investigate; does not explain why |
| Reverts and `supersedes` evidence | Changes in direction that may warrant an ADR | Medium | Needs explicit detection and interpretation rules |

PRs, issues, and session logs are candidates for richer rationale. Churn is a way to choose
where to look, not evidence of a reason on its own.

## How mining joins the harness

Mining uses the **existing ADR draft contract**, not a new schema, and follows the same
promotion path as forward capture: `_pending/decisions/` → `/memory-update` §1.6 → shared
`decisions/` and its index.

```text
Implemented: git commit-message slice ─┐
                                      ├→ LLM → _pending/decisions/*.md
Planned: PR/issue/session evidence ────┘          proposed_chain
                                                proposed_supersedes
                                                confidence
                                                     ↓
                                        human review with /memory-update
                                                     ↓
                                          decisions/ + INDEX.md
```

- **Shared implementation:** `mine.py` already reuses `reflect.py`'s draft contract, backends,
  parser, classifier, and `_decisions_index`. It is another draft generator whose input is a
  Git slice instead of a transcript.
- **Canonical schema:** the full ADR schema is inline in
  [`core/skills/memory-update/SKILL.md`](../core/skills/memory-update/SKILL.md), §1.6, and is
  rendered into both plugins. Shipping that schema was completed in
  [PR #137](https://github.com/foxyberry/agent-harness/pull/137). Existing projects may still need
  template updates; do not confuse that rollout issue with a missing plugin schema.
- **Engine/data separation for future selection rules:** project-specific choices about which
  commit patterns indicate decisions should live in project data, such as a proposed
  `decision-mining-rules.json`. That file and its schema are **not implemented**; the current
  CLI takes a user-selected revision range and uses a generic extraction prompt.
- **Relationship to `fw`:** `fw` reads session logs to resume work. Future mining could reuse
  those readers to extract decisions, but the consumer's purpose and provenance requirements
  differ. No session-log input is wired into the current mining CLI.

## Constraints

1. **No recorded rationale, no justified decision draft.** Mining must not invent why a choice
   was made. The prompt tells the model to skip commits without evidence instead of forcing an
   ADR from every change; human review must enforce that expectation.
2. **Incorrect decision relationships are a serious failure.** Chain membership and supersession
   are proposed through `proposed_*` fields. As with forward capture, a person must confirm them
   during promotion; mining cannot establish the canonical history automatically.
3. **Mining and retrospectives complement each other.** Mining can seed an incomplete past;
   forward capture records rationale while it is still available. Neither makes the other
   unnecessary.
4. **Require positive evidence.** Uncertain decision signals should not be promoted into context
   as facts. An empty result is preferable to a fabricated ADR.

## Remaining work

- [ ] Extend the commit-message CLI with PR and issue evidence, then evaluate session-log inputs.
- [ ] Define a project-owned `decision-mining-rules.json` schema if configurable signal selection
  is added.
- [ ] Evaluate mined drafts against known decisions in this repository, including the original
  proposed benchmark PRs #6, #13, and #16.
- [ ] Validate multi-source provenance and proposed chain/supersession relationships before
  expanding automatic behavior.

The commit-message CLI and reuse of the retrospective draft machinery are already implemented;
these checkboxes describe the remaining expansion, not an entirely unbuilt feature.

## Related material

- [Issue #15](https://github.com/foxyberry/agent-harness/issues/15): original exploration and
  historical market notes.
- [Issue #14](https://github.com/foxyberry/agent-harness/issues/14) and
  [PR #16](https://github.com/foxyberry/agent-harness/pull/16): forward capture.
- [Self-improvement hooks](self-improvement-hooks.md): the retrospective loop and promotion path.
- [`mine.py`](../core/hooks/mine.py) and [`reflect.py`](../core/hooks/reflect.py): current mining
  implementation and shared draft machinery.
- [`memory-update` §1.6](../core/skills/memory-update/SKILL.md): canonical ADR schema and promotion
  procedure.
