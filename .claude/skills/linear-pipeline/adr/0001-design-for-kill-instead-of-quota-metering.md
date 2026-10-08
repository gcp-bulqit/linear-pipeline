# Design for kill instead of metering the quota

The pipeline's original premise was that a supervisor would monitor and throttle the other agents'
consumption so that exhausting the team usage limit never interrupted work. Inspection of Claude
Code v2.1.248, at the time of writing, established that this is not buildable: there is no programmatic readout of remaining
team session quota (`/usage` is an interactive in-session view, `--max-budget-usd` applies to
API-key billing only), and a parent agent cannot observe a subagent's token usage — it sees only the
text the subagent returns. We therefore abandoned metering entirely and adopted **design-for-kill**:
assume termination at any instant, and make the loss bounded by how recently work was persisted.

## Consequences

Almost every other decision in this system follows from this one. Incremental writes, the paired
state machine (ADR-0005), commits-as-checkpoints, the lock's mandatory stale timeout, and the rule
that subagents have no network side effects all exist to serve it. Context control in this system is
strictly *preventive* — bounding what is handed in and what may be handed back. Any future claim
that the supervisor "manages", "monitors" or "throttles" usage is false and should be removed.

We also rejected a self-estimated cost counter (stage count × rough per-stage cost). It has no
ground truth, would drift, and would give false confidence — which is worse than the honest
admission that consumption is invisible.
