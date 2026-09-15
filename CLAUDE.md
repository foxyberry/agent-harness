# CLAUDE.md

The canonical guidance for this repository is **[AGENTS.md](./AGENTS.md)**. Read and follow that first.

@AGENTS.md

## Claude-only notes

- Claude Code does not read AGENTS.md natively, so this pointer is required (hence the `@AGENTS.md` import).
- The Claude adapter = `plugins/harness/` (published through the root `.claude-plugin/marketplace.json`).
- `core/` is the canonical source for skills and hooks → `./build.sh` copies them into `plugins/harness/`. Reference only paths inside the plugin folder (`${CLAUDE_PLUGIN_ROOT}`); never use `../`.
