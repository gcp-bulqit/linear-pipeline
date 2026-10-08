---
status: accepted (checkpoint rationale partly superseded by ADR-0010; the one-active-issue rule superseded by ADR-0014)
---

# One worker per issue, no plan fan-out

The original design allowed "one or more worker agents in a worktree". We reduced it to exactly one
worker, executing plan steps sequentially in a single worktree.

Multiple workers in one worktree conflict: two agents editing the same file with no coordination
corrupt each other's work, and there is no merge step to catch it. The fan-out alternative — one
worktree per worker, merged at the end — is legitimate, but it adds a parcel-independence contract,
a merge strategy and conflict resolution, none of which v1 needs. The file-ownership variant, where
the planner partitions files between workers, avoids merging but fails silently whenever the
partition is imperfect.

## Consequences

Sequential execution is not merely a simplification: the worker's per-step commits are the system's
checkpoint mechanism under ADR-0001, and a single linear branch is what makes resuming at the first
uncommitted step unambiguous.

**Amended by ADR-0010.** Commits now honour the repo's pre-commit hooks, so a step whose work cannot
pass them cannot be committed. The checkpoint is coarser than this ADR originally assumed, and
uncommittable work is stashed rather than lost. The reasoning for one worker and one linear branch is
unaffected.

For the same reason, only one issue is **active** at a time, which also keeps the supervisor's
context flat with respect to queue length. Parked issues do not count as in flight.

**Amended by ADR-0014.** Up to `limits.maxConcurrent` issues may now be active, each in its own slot with
its own worktree, branch and database, and with one verify gate at a time across slots. One worker and
one linear branch per issue are unchanged.

Fan-out is a deliberate v2 item, not a gap. Anyone proposing it should expect to design the merge
strategy and the resume story together.
