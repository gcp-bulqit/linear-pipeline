# Retrospectives are local scratch; only curated notes are committed

Per-issue working material lives under `.issues/`, which is gitignored, while durable knowledge
lives in curated notes under `docs/`, which are committed onto the feature branch. The retrospective
that a documentation agent writes for each issue stays on the ignored side.

This looks like an oversight and is not. We first intended retrospectives to be a committed audit
trail alongside the curated notes, then hit a git constraint: excluding a directory prevents
re-including files inside it, so "ignore `.issues/` except the retrospective" is not cleanly
expressible. Given the choice between intricate ignore rules that are easy to get subtly wrong and a
rule with no exceptions, we took the rule with no exceptions.

## Consequences

`.issues/` is entirely ephemeral and private; `docs/` is entirely durable and committed. Nothing
straddles the line.

The retrospective is therefore **not** an audit trail. It is working material from which a curated
note is written, plus a local aid to future discovery runs on the same machine. The only knowledge
that reaches a teammate is a curated note — so if something matters, it belongs in one. Anyone
tempted to start relying on retrospectives as a team-visible record should promote the content
instead.

Curated notes commit onto the feature branch rather than the default branch, so learnings from work
that is ultimately **rejected** are never published: they arrive only if the pull request merges.
