## Executor mode (when invoked via `codex exec`)

When you are launched headlessly via `codex exec` for a `tandem` task, you are the EXECUTOR,
not the orchestrator:
- Work ONLY inside the given worktree; never touch other paths.
- Use TDD; after green, do a scoped `chore: cleanup` commit (dead code/docs out, lint clean).
- Run this repo's typecheck + lint + tests until green; return the structured summary.
- DO NOT open PRs, merge, push to main, or deploy — the orchestrator (Claude) owns shipping.
