# Stages record both start and completion

Every agent-invoked stage writes a `*_STARTED` marker before dispatch and a `*_COMPLETE` marker
after the agent returns. The alternative — recording only completed stages — is half the writes and
a simpler file, and we rejected it.

The reason is specific to ADR-0001. A run killed mid-stage leaves a partial artifact on disk. With
completion-only state there is no record that it is partial, so a resumed run reads a truncated
findings document or half a plan and feeds it to the next stage as though it were finished. Paired
states make that case detectable: a `*_STARTED` marker found on resume means the artifact is
**suspect**, and its stage is re-run from scratch.

## Consequences

Write ordering is part of the contract, not an implementation detail: `*_STARTED` before dispatch,
`*_COMPLETE` after the status line returns. A kill anywhere between them must leave `*_STARTED` on
disk.

Two exceptions. Supervisor-local git operations are recorded as single milestones, because they are
idempotent-checkable — an existing worktree or an existing pull request can simply be detected — so
a started marker would add writes with no resume value. And the worker is exempt from "re-run from
scratch": its commits are self-describing checkpoints, so it resumes at the first plan step with no
commit.
