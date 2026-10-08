---
status: accepted (amends ADR-0008)
---

# Bounded concurrency across issues, one gate at a time

ADR-0008 kept exactly one issue active at a time. It gave two reasons: one worker and one linear branch
per issue make the checkpoint and the resume unambiguous, and one active issue keeps the supervisor's
context flat with respect to queue length.

The first reason is about the inside of an issue, and it stands unchanged. The second turned out not
to need one active issue. The by-reference discipline already makes each in-flight issue cost the
supervisor one status line per stage, so several issues cost several lines, not several documents.

What one active issue did buy, without saying so, was exclusive use of everything the worktrees share.
Separate issues already get separate worktrees and branches, so they never need merging. The
collisions come from the resources underneath. A real drain of the queue showed what one active issue
cost and what concurrency would break.

## What one active issue cost

Every operator-only step stalled the whole queue. An expired signing-key passphrase, read-only production queries
the sandbox could not reach, and questions about behaviour changes each held every queued issue behind
one person's reply, for hours at a time. The operator was not the bottleneck on work; the pipeline made
them the bottleneck on everything.

## What concurrency would break, and the answer to each

| Shared resource | Failure | Answer |
|---|---|---|
| Local database (e.g. Postgres) | Integration tests truncate every table and branches apply their migrations to one database, so two gates corrupt each other | One database per slot, cloned from a template (`database.*`, `scripts/slot_db.py`) |
| CPU | Timing-sensitive tests fail under load | One gate at a time across all slots (`gate` mutex in the state file) |
| Build/test cache (e.g. Turborepo) | A gate can replay a cached pass from a sibling worktree | A cache directory per slot (`gate.perSlotEnv`, e.g. `TURBO_CACHE_DIR`) |
| Migration numbers | Concurrent planners take the same migration number from the base branch | At most one migration-bearing issue past discovery (`footprint.json`) |
| Shared files | Two branches editing one file conflict at merge, and neither reviewer sees the other change | No two slots past discovery with overlapping footprint paths |
| The operator | One slot's question stalls all of them | `WAITING_OPERATOR` holds only that slot |

## Decision

Up to `limits.maxConcurrent` issues are in flight at once, each in a numbered slot that owns its
worktree, its branch and its database. Within a slot nothing changes: one worker, one linear branch,
the same transition table and the same resume rules.

Admission is checked after discovery, because discovery is read-only and is what produces the
footprint. An issue that collides with a slot past discovery waits at `DISCOVERY_COMPLETE`, holding
its slot, until the other slot frees. A missing footprint is treated as colliding with everything.

The verify gate runs one slot at a time. Planning, implementation, review and documentation run in
parallel; the gate is the only stage serialised, because it is the only one that loads the machine and
the only one whose result must not depend on what else is running.

The default for `limits.maxConcurrent` is 1, which reproduces ADR-0008's behaviour exactly.

## Consequences

**Throughput is bounded by the gate.** With five slots and one gate, the steady state is several slots
waiting at `IMPLEMENTATION_COMPLETE`. That is acceptable: agent stages, operator waits and review are
where the time went, and those now overlap.

**The state file has a new shape.** `active` became `slots`, keyed by slot number, plus a `gate` field.
A pre-0014 state file is migrated at startup by moving `active` into slot 1.

**Slot numbers are durable.** A slot keeps its number for its issue's whole life, because the number
names its database. A parked issue releases its slot; when it unparks, it takes whatever slot is free
and that slot's database is reset.

**Footprints are declarations, not proofs.** Discovery and the planner say which paths an issue will
touch. A worker that strays outside its footprint can still collide with another slot. The reviewer
compares the diff to the footprint, and a stray is a finding.

**The template needs maintenance.** Slot databases clone `database.slotTemplate`. The template must be
rebuilt after the base branch gains migrations, and only when no slot is past planning.

## Rejected

**Fan-out within one issue.** Still out of scope, for ADR-0008's reasons. This ADR is concurrency
across issues only.

**Parallel gates with a CPU budget.** It would need a model of each suite's load and would still flake
the timing-sensitive tests. One gate at a time is simple and correct.

**A shared database with per-slot schemas.** In the first target repo the migration runner, the test harness and the app all
assume the `public` schema. Per-slot databases need no code change in the repo.
