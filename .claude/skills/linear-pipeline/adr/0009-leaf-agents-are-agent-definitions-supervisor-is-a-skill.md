# Leaf agents are agent definitions; the supervisor is a skill

The five leaf roles — discovery, planner, worker, reviewer, documentation — are `.claude/agents/pipeline-*.md`
definitions. The supervisor is a skill, `/linear-pipeline`. We considered making all six agent
definitions, all six skills, or one skill holding six inline prompts.

The split follows from what each format can express. **Both** formats enforce a tool allowlist —
agents via `tools`, skills via `allowed-tools`, both supporting scoped entries like
`Agent(a, b)` and `Bash(git *)` — so tool restriction was never the differentiator. What agents have
and skills do not is **`effort`**, alongside per-definition `model`. Since spending the expensive
model only where judgment lives is this design's main quota lever (and the only one that costs no
correctness), the roles whose model and effort must differ belong in agent definitions.

The supervisor is a skill because it is the entry point: user-invoked, argument-taking, and its body
is a long procedural loop, which is what a skill body is for. It loses per-definition `effort`, which
costs nothing — it does no reasoning about content, only routing.

## Consequences

The eight-part contracts written during design are **promoted** into the agent files and become the
live prompts. The design documents stay behind in the framework repository (under `docs/`) as the
account of *why*, together with these ADRs. There is
no second copy to drift, and the Anti-goals sections do their work as prompt text.

The supervisor has no `effort` setting and no `models` entry in config: it runs on the operator's
session model. If that matters, the operator sets it with `/model` before invoking.

The supervisor's `allowed-tools` is where the Linear identity separation of ADR-0012 is actually
enforced. It names the five agents explicitly and omits the operator's Linear connection entirely.

`.claude/agents/` and `.claude/skills/` are committed to the target repo, under the same
shared-definition rule as the rest of the framework.
