# Documentation

Background documentation for the Linear pipeline (`/linear-pipeline`): a Claude Code skill that
supervises five agents to take Linear issues through discovery, planning, implementation, an objective
verify gate, adversarial review and documentation, ending in a draft pull request.

For installation and configuration, start with the repository's top-level README and the field
reference in [`config.md`](../.claude/skills/linear-pipeline/config.md). The documents here explain
how the system works and why.

| Document | Read it to learn |
|---|---|
| [architecture.md](architecture.md) | How it works: the agents and their contracts, the supervisor's two disciplines, the stage machine and attempt loop, parking and escalation, concurrency (slots, footprints, the gate mutex, per-slot databases), the clock and lock, kill and resume, what is written to Linear, and where artifacts live. Includes the system diagrams. |
| [design-history.md](design-history.md) | How the design evolved, from a one-paragraph idea through two design sessions, prompt hardening and first runs, to the clock and bounded-concurrency ADRs. Includes the table of rejected alternatives. |
| [lessons.md](lessons.md) | Twenty-six lessons from real runs, each as what happened, why it mattered, the fix and the principle. |
| [run-statistics.md](run-statistics.md) | Measured results from about five weeks against a production Next.js/TypeScript monorepo: 131 pipeline PRs, attempts, throughput (single-slot and five-slot), latency, PR size, review findings and triage, with method notes and caveats. |

## Related material in the repository

| Path | What it is |
|---|---|
| [`.claude/skills/linear-pipeline/SKILL.md`](../.claude/skills/linear-pipeline/SKILL.md) | The supervisor prompt: the source of truth for behaviour |
| [`.claude/agents/`](../.claude/agents/) | The five leaf agents |
| [`.claude/skills/linear-pipeline/adr/`](../.claude/skills/linear-pipeline/adr/) | Fourteen architecture decision records |
| [`.claude/skills/linear-pipeline/reference/`](../.claude/skills/linear-pipeline/reference/) | The decision-brief and pull-request formats |

## Suggested reading order

1. The overview and topology diagram at the top of [architecture.md](architecture.md).
2. [lessons.md](lessons.md), which shows where the design met reality.
3. The ADRs, for the reasoning behind any single rule.
4. [design-history.md](design-history.md) and [run-statistics.md](run-statistics.md) as needed.

## Diagrams

The diagrams are written in Mermaid and render on GitHub. Every block was validated with
`@mermaid-js/mermaid-cli`.
