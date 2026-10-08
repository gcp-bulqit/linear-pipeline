# Linear Issue Pipeline

An agent pipeline that takes filtered Linear issues through discovery, planning, implementation and
adversarial review to a draft pull request, keeping each task's working material in the target
repository's file structure rather than in any agent's context window. It is built to be killed
mid-run by a usage limit (for example a team plan's shared session quota) and resumed later
without losing completed work.

## Language

### The work

**Issue**:
A Linear ticket that has entered the pipeline. Always referred to by its Linear ID.
_Avoid_: task, ticket, story, item

**Run**:
One invocation of the pipeline by a human, from acquiring the lock to releasing it. A run ends
normally, or is killed by the usage limit.
_Avoid_: session, job, execution

**Stage**:
One step of the pipeline performed by exactly one agent — discovery, planning, implementation,
verification, review, or documentation.
_Avoid_: step, phase, task

**Attempt** (**cycle**):
One pass around the review → planning → implementation loop for a single issue. Numbered from 1, and
counted by a **single** counter that a failed verification and a failed review both increment.
Distinct from a **Linear cycle**, which is a sprint; this system does not read Linear cycles.
_Avoid_: iteration, round, retry, sprint

**Re-discovery**:
Re-running discovery mid-issue because a review showed the understanding was wrong rather than the
implementation. Capped per issue: a second request is a blocked issue, not another attempt.
_Avoid_: re-research, re-investigation

**Step**:
One numbered instruction in a plan. Reserved for that meaning only; a stage is not a step.

### The agents

**Supervisor**:
The agent that owns the queue and the stage machine, routes work between the other agents, and
performs every git and Linear operation. It is the only agent that acts outwardly.
_Avoid_: orchestrator, coordinator, manager, meta agent

**Leaf agent**:
Any agent that is not the supervisor. Leaf agents are dispatched, never dispatch; they read and write
files and return a status line, and none of them acts outwardly.
_Avoid_: sub-agent, child agent, worker (which names one specific role)

**Discovery**:
The agent that reads a ticket and the codebase and produces a findings document. It reports what
is, never what should be.
_Avoid_: research agent, investigator, explorer

**Planner**:
The agent that turns a findings document into an ordered, verifiable plan.
_Avoid_: planning agent, architect, designer

**Worker**:
The agent that executes a plan's steps in a worktree, committing after each one.
_Avoid_: implementer, builder, coder, executor

**Reviewer**:
The agent that adversarially reviews a change against its plan and the surrounding codebase, and
classifies what it finds by severity.
_Avoid_: critic, QA, auditor

**Documentation agent**:
The agent that produces the curated note and the retrospective after a change passes review.
_Avoid_: scribe, historian, writer

### Artifacts

**Findings document**:
Discovery's output: a compressed description of what the ticket asks for and how the relevant code
works, so that nothing downstream must read source to plan.
_Avoid_: research, report, analysis, context dump

**Plan**:
The planner's output: a goal, an approach, ordered steps and acceptance criteria. **The plan is the
handoff brief** — it must be executable by a worker that has read nothing else.
_Avoid_: spec, design, ticket breakdown

**Handoff brief**:
Not a separate artifact. A synonym for the plan, naming the property that makes a plan valid: it
carries everything its recipient needs. Prefer "plan" in running text.

**Decision brief**:
The comment the supervisor posts to Linear when an issue is parked. Carries situation, options,
recommendation, the question, and a state pointer — enough for a person or a fresh agent to act
without reading the working material.
_Avoid_: escalation, question, blocker comment, handoff

**State pointer**:
The section of a decision brief naming the issue, stage, attempt and artifact paths. It is what
makes a brief resumable rather than merely readable.

**Worklog**:
The worker's ledger: one entry per step with its commit and verification outcome. A record, not a
narrative.
_Avoid_: log, journal, diary, progress notes

**Review**:
The reviewer's output document. Reserved for the reviewer's work; a human's assessment of the draft
pull request is not a review in this vocabulary.
_Avoid_: critique, feedback, assessment

**Curated note**:
A durable, committed document under `docs/` describing how part of the system works, written so a
future discovery stage costs less. Editing an existing note beats adding a new one.
_Avoid_: base context, learnings, knowledge base article, wiki page

**Retrospective**:
Local working material summarising how one issue went, from which a curated note is written. It is
scratch, never a durable record, and never reaches a teammate.
_Avoid_: post-mortem, audit trail, history

**Status line**:
The single line an agent returns to the supervisor: a status, an artifact path, and any routing
flags. It is the entire quantity of an agent's output the supervisor absorbs.
_Avoid_: result, response, summary, return value

### Issue lifecycle

**Active**:
An issue a run is currently moving through stages, in one of its slots. There are at most
`limits.maxConcurrent` (ADR-0014).
_Avoid_: current, running, open

**Slot**:
A numbered place for one active issue. It owns that issue's worktree, branch and local database
(`<database.slotPrefix><n>`, when a `database` block is configured), and keeps its number for the
issue's whole life. Free slots are absent from `slots`.

**Footprint**:
`.issues/<ID>/footprint.json`: whether the issue needs a migration, and which paths it will touch.
Discovery writes it and the planner may widen it. Admission compares footprints across slots.

**Gate holder**:
The one slot whose verify gate is running. Gates never run concurrently.

**Waiting on the operator**:
A slot held at `WAITING_OPERATOR` for an operator-only step such as unlocking a signing key or a
query the sandbox cannot run. It is still active and keeps its slot, unlike a parked issue, and
nothing is posted to Linear.

**Held**:
An issue set aside at close-out while still waiting on the operator, with the check that ends the
wait. The next cold start resumes it once the check passes. Unlike a parked issue, nothing was posted
to Linear.

**Not code**:
An issue whose resolution would produce no commit in this repository: a dashboard setting, a data fix,
a question. Under `codeChangesOnly` it is left where it is, recorded locally, and never commented on.

**In flight**:
Active. Parked and escalated issues are explicitly **not** in flight — they consume nothing while
waiting.

**Parked**:
Set aside awaiting a human, and no longer in flight. An issue parks when it is blocked or escalated.
_Avoid_: paused, stalled, waiting, on hold

**Blocked**:
An agent reached a genuine fork it cannot resolve — two defensible readings, a missing acceptance
criterion, a product call — and stopped rather than guessing. Distinct from escalated.
_Avoid_: stuck, failed, needs input

**Escalated**:
The attempt cap was reached without the goal being met. Distinct from blocked: nothing is being
asked, the loop simply ran out.
_Avoid_: timed out, gave up, failed

**Unparked**:
Returned to the queue because a human answered. Their answer becomes the input to a re-run of the
stage that stopped.
_Avoid_: resumed, unblocked, reopened

### Review and verification

**Review finding**:
One claim in a review, classified blocking or advisory. Discovery does not produce findings — it
produces a findings document, which is a description, not a list of claims.

**Blocking**:
A review finding that must be resolved before the goal is met. Permitted only for correctness,
security, or an unmet plan requirement — never for taste. An arguable finding is advisory.
_Avoid_: critical, must-fix, P0

**Advisory**:
A review finding worth recording but not worth another attempt. Advisory findings travel to the
pull request description and never re-trigger the loop.
_Avoid_: nit, minor, suggestion, nice-to-have

**Objective gate**:
The ordered list of verification commands the operator configured, run by the supervisor. Deliberately
separate from review: it is the half of "done" that cannot be argued with.
_Avoid_: CI, checks, validation, quality gate

**Verify entry**:
One named command in the objective gate. Named so that a failure says which gate failed, and ordered
so the cheapest fails first.

**Goal met**:
Zero blocking findings, a green objective gate, and every plan step complete. The only definition of
done.
_Avoid_: finished, complete, passing, shipped

### Operation

**Pipeline Bot**:
The Linear identity the pipeline writes as, distinct from the operator's. Issues assigned to it are
the intake filter, and its authorship is what lets a teammate tell a machine comment from a person's.
_Avoid_: the bot, service account, agent user

**Setup mode**:
What the supervisor does instead of running when no configuration exists: propose settings detected
from the repository, confirm them, write the configuration, and stop.
_Avoid_: init, bootstrap, onboarding, install

### Survival

**Design-for-kill**:
The stance that any agent may be terminated mid-sentence when a usage limit is reached, so
correctness depends on what has been written to disk rather than on finishing.
_Avoid_: fault tolerance, resilience, graceful degradation

**Quota kill**:
Termination caused by a usage limit being reached. Cannot be predicted, caught, or cleaned
up after.
_Avoid_: rate limit, throttle, timeout, crash

**Checkpoint**:
A point past which work survives a quota kill. For most stages this is an incremental write to an
artifact; for the worker it is a commit, which must pass the repository's commit hooks — so work that
cannot pass them is stashed rather than checkpointed.
_Avoid_: save point, snapshot, milestone

**Stashed step**:
Work from a step that could not be committed because the repository's hooks rejected it, set aside
under a message naming the issue and step. Resume inspects the stash before re-running the step.
_Avoid_: WIP, dirty work, pending changes

**Suspect**:
The condition of an artifact whose stage began but never completed. A suspect artifact is discarded
and its stage re-run; it is never consumed.
_Avoid_: partial, incomplete, dirty, stale
