# decisions/ — decision records (ADR)

This folder holds one record per **"why we decided it that way"**. Code shows only *what* was
done — an ADR (Architecture Decision Record) is what stops "why is this like this?" from
evaporating out of someone's head six months later. The retrospective loop writes drafts into
`_pending/decisions/`, and a person promotes them with `/memory-update`.

## The schema is not here

**The canonical copy lives in the `memory-update` skill body (§1.6).** This file only explains
what the folder is for; it does not restate the schema.

The reason is something this very file caused. The skill used to point at this file as the
"canonical schema", but the plugin did not ship `project-template/`. So in a project that had
not copied this pack — or had copied it before the ADR feature existed — **the canonical copy
pointed at a file that did not exist**, and promotion was blocked (issue #132). The plugin now
ships a read-only copy of this template's `.claude/memory/` for `/template-check` to compare
against, but it is never installed into a project and is not a schema source either. The schema is a
format the harness defines, not something that varies per project, so it has to live where it
ships with the harness.

- **Schema, gates and link rules** → `memory-update` skill §1.6 (shipped with the plugin)
- **The actual decision files in this folder** → owned by the project. Commit them so the team shares them

## Example

One example is included, `adr-EXAMPLE-positive-only-exclusion.md`. It is there so you can see the
format, and the retrospective automation **excludes it from its input** whenever `EXAMPLE` appears
in the file name — this keeps the example from being fed to the LLM as a "real existing decision"
and proposed as a supersedes candidate.

In a new project you may delete this example or keep it.

## What belongs in an ADR

Something is an ADR only if you can write **both** `## Alternatives` (the options you did not take)
and `## Consequence` (the outcome). If you cannot, it is not a decision but a lesson or a rule, so
send it to `patterns/` or to ordinary memory. Turning every choice into an ADR destroys search.
