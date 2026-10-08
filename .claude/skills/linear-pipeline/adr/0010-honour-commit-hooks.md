---
status: accepted
---

# Worker commits honour the repo's commit hooks

Worker step commits run the target repo's pre-commit hooks like any human commit. We considered
`--no-verify` for step commits with one hook-honouring commit at the end, and rejected both
alternatives.

The forcing fact was the first target repo's configuration: its lefthook pre-commit hook ran lint
and typecheck with `stage_fixed: true`. A commit whose types fail is **rejected**,
and lint auto-fixes and re-stages files mid-commit. So the design's original rule — that a red commit
is permitted and expected, because committing red preserves the checkpoint — is not merely
undesirable here, it is impossible. Rather than route around the repo's own gates with `--no-verify`,
we accepted them: every commit on an agent branch is green, exactly like a human's.

## Consequences

**This supersedes the red-commit rule in ADR-0008.** Per-step commits are still the checkpoint
mechanism, but the checkpoint is now coarser: work that cannot pass the hooks cannot be committed,
so a kill mid-step would strand it. Work that cannot be committed is therefore **stashed** with a
message naming the issue and step, and resume inspects the stash before re-running the step. History
stays green; work is not lost.

The worker's per-step targeted check narrows to **tests only**. Lint and typecheck arrive free with
the commit, and running them twice per step would be pure waste.

The worker must expect its files to be modified during commit by auto-fixing hooks (lefthook's
`stage_fixed`, lint-staged and the like), and must not treat that as a failure or an unexpected edit.

Cost is lower than it looks: task-runner caches (Turborepo, Nx and the like) make the second and
subsequent hook runs on unchanged packages near-instant.

A commit can also fail for a reason no edit will fix: a repository that requires signed commits
refuses one when the signing key is locked. That work is stashed exactly as hook-rejected work is,
and the slot waits on the operator (`WAITING_OPERATOR`) rather than spending retries.
