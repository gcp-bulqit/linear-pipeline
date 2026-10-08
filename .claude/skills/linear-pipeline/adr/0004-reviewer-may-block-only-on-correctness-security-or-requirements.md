# The reviewer may block only on correctness, security, or an unmet requirement

The reviewer is instructed to be adversarial, and an adversarial reviewer can always find something.
If passing required the reviewer to be satisfied, the review → planning → implementation loop would
have no reliable terminating condition and every issue would burn to the attempt cap. We therefore
narrowed the reviewer's *authority* without narrowing its *thoroughness*: it may classify a finding
as blocking only for correctness, security, or an acceptance criterion in the plan not being met.
Everything else — style, naming, structure, "I would have done it differently", speculative future
problems — is advisory, travels to the pull request description, and never triggers another attempt.

## Consequences

An arguable finding resolves to advisory, deliberately. The cost is asymmetric: a wrong blocking
call burns a full attempt of a scarce quota, while a wrong advisory call costs a line in a PR body
that a human skims.

"Done" is therefore a two-part predicate — zero blocking findings **and** a green objective gate —
and the objective half is run by the supervisor, not the reviewer. Folding verification into the
review would re-merge the subjective and objective gates that were split apart precisely to
guarantee termination.
