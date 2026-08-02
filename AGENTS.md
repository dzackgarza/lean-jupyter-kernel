# AGENTS.md

Use SDL-MCP as the default path for repository `lean-jupyter-kernel`.

## SDL-MCP Skill Bootstrap

At the start of every new session in this repository, load and follow the
`sdl-mcp-agent-workflow` skill before repository exploration, command
execution, or edits. If the client cannot load skills, follow that skill's
bundled fallback rather than a repo-local copy.

When the SDL-MCP PID file is present, treat native repo-local shell and file
tools as fallback-only. Use SDL runtime for shell actions with `stdin` for
multiline input, the Iris ladder for indexed reads, `symbol.edit` for
one-symbol indexed writes, `searchEditPreview` with
`targeting:"identifier"`/`"structural"` or `operations[]` for cross-file
indexed edits, and `file.read`/`file.write` for non-indexed files. Native
access is reserved for `.codex/**`, `.claude/**`, and non-repo agent skills,
memories, and session internals.

SDL-MCP (Symbol Delta Ledger MCP Server) - an MCP server providing cards-first
code context for polyglot repositories. Replaces bulk code reads with
structured symbol cards, graph slices, delta packs, and gated code windows.
Uses LadybugDB (graph DB), tree-sitter (AST parsing), and optional Rust native
addon (napi-rs) for performance.

<!-- agent-memory:start -->
# Agent memory

This repository uses the central agent memory vault at `/home/dzack/.agent-memory-vault`.

Project memory key: `projects/github.com__dzackgarza__lean-jupyter-kernel/index`.

Repository `.agents` and `.hermes` paths are symlinks to the same vault-owned project directory.

Before changing architecture, search both project and global memory:

```bash
agent-memory search --scope both "<task or subsystem>"
```

Record durable repo-specific lessons with:

```bash
agent-memory add --scope project --type decision --title <title> --content <content>
agent-memory add --scope project --type trap --title <title> --content <content>
agent-memory add --scope project --type advice --title <title> --content <content>
agent-memory add --scope project --type context --title <title> --content <content>
agent-memory add --scope project --type reference --title <title> --content <content>
```

Plan work is card-backed. Create and update plan cards with `agent-memory plan add` and `agent-memory plan update`, not `agent-memory add --type plan`.

Use `agent-memory retrieve <key>`, `agent-memory update <key>`, and `agent-memory delete <key>` for memory CRUD.

The vault should be committed at all times. Treat staged or unstaged vault changes as an ephemeral error state. Before normal memory work resumes, load the bundled vault-maintenance skill with `agent-memory maintain skill vault-maintenance` and follow its referenced check, repair, and commit workflows.

Move reusable lessons during maintenance with:

```bash
agent-memory maintain move <key> --to global/advice
```
<!-- agent-memory:end -->
