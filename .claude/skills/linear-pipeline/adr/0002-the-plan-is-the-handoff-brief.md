# The plan is the handoff brief; there is no handoff agent

The original design had a separate handoff agent that turned a sufficiently-specified issue into
goals, context and scope for a worker. We removed it: handoff is a document format, not a role. The
planner's output contract *is* the handoff brief, which deletes an entire hop of context-copying
between agents.

The original flow also placed the handoff agent on only one of two paths — an issue with enough
context reached it, but a plan went straight to a worker — so it was structurally dead weight on
half the pipeline. Collapsing it into the planner resolved that rather than papering over it.

## Consequences

The planner carries a hard obligation in exchange: a plan must be executable by a worker that has
read **only** the plan — never the ticket, never the findings, never the review. If a worker needs
something the plan does not carry, that is a planner defect, and the worker records it in the
worklog so the failure is visible rather than silently absorbed.
