# Discovery always runs

The original design had the supervisor decide whether an issue carried "sufficient context" and
route it to planning or to further investigation accordingly. We deleted that branch: discovery runs
on every issue, unconditionally.

Two reasons. First, for the supervisor to judge sufficiency it would have to read the ticket body in
detail — the exact context absorption the whole system is built to avoid, and a direct violation of
the supervisor holding no content. Second, the judgement fails in the expensive direction: routing a
vague ticket straight to planning wastes a full attempt, while running discovery on a clear ticket
costs one fast stage on the cheap model.

## Consequences

The supervisor never reads a ticket body, only an ID. Discovery is expected to self-terminate
quickly on clear tickets — a terse findings document is a success, not a failure. We accept spending
a stage on issues that did not need one; this is a known, deliberate cost, not an oversight to
optimise away later.
