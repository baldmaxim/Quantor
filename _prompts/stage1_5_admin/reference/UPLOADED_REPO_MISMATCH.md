# Uploaded repository mismatch noticed during external review

The simultaneously uploaded archive named `LocalAI-main.zip` does not match the QTO Portal repository described in the Stage 1 handoff.

Observed archive top-level code:

```text
apps/rag-api
apps/rag-ui
apps/mcp-server
config
scripts
tests
```

Its README identifies it as `LOCAL RAG` and its package scripts start `apps/rag-api/src/server.js`.

The Stage 1 QTO handoff expects:

```text
apps/api/app
apps/web/src
packages/api-client
docs/adr
CLAUDE.md
```

Therefore no code-level claim about the QTO implementation should be based on `LocalAI-main.zip` unless the correct QTO repository is provided/opened.

Prompt 00 prevents accidental changes to the wrong repository.
