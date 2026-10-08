# The supervisor is the only agent that writes to Linear or git

Subagents never post to Linear, never push, never open pull requests. When an agent hits a fork it
cannot resolve it writes a decision brief to a file and returns a blocked status; the supervisor
reads that file and posts the single Linear comment. Git plumbing — worktree, branch, push, PR — is
likewise the supervisor's alone, which is safe because those operations are content-free and so do
not breach the rule that the supervisor holds no artifact contents.

The alternative, letting each agent speak for itself, produces richer briefs with no handoff loss.
We rejected it for two reasons: Linear is a shared human workspace where every write is visible to
teammates, so outward actions belong at one auditable choke point; and, more sharply, a subagent
with network side effects is no longer safely re-runnable — under ADR-0001 a killed stage is re-run,
and a stage that posted a comment before dying would post it twice.

## Consequences

Linear receives decisions, not a progress log: status on pickup, the pull request link on
completion, and one comment on block or escalation. Rich per-stage commentary was considered and
rejected as noise for human teammates.

The pipeline's terminal state is a **draft** pull request. It never merges, never force-pushes, and
never writes to the default branch.
