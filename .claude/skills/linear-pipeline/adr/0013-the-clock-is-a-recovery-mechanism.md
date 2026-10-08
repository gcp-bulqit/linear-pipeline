# The clock is a recovery mechanism, not a scheduler

Until now the pipeline had exactly one thing that could wake a sleeping supervisor: a background
agent's completion notification. Dispatch, end the turn, sleep, get woken by the agent finishing.
That chain is fast and costs nothing when it holds, and it is the reason the design needed no timer.

Measurement on a real drain of the queue showed it is also a single point of failure. Across one
session the supervisor ended 199 turns and every halt that required a human to restart the run traced
to the same cause: the chain was broken and nothing else could restart it. Six breaks, all originating
at the keyboard, three interrupts, two stopped agents and one context clear. Nothing crashed, no
process was killed, the kernel OOM counter was zero. Interrupting a running agent guarantees its
completion notification never arrives, so the loop does not stall, it dies, and it dies quietly.

The design already assumed termination at any instant (ADR-0001) and answered it with
recoverability: what is on disk survives. That answer is complete for *state* and silent about
*continuity*. A run could always be resumed correctly, but only by a human noticing it had stopped and
typing the skill's name again.

So the pipeline now arms a fallback wake after each dispatch, 1200 to 1800 seconds out. The mechanism
is Claude Code's `ScheduleWakeup` tool, available when the skill runs under `/loop` in dynamic mode;
stopping the clock means not scheduling the next wake.

## The clock does not schedule work

Agent completions remain the primary path and deliver every bit of the throughput. Median agent
runtime measured 3.5 minutes, so a timer fast enough to compete would mostly fire into work that is
still running, and a timer slow enough to be cheap would add idle gaps that notifications do not have.
The timer exists to notice that the notification chain has stopped, and for nothing else. Shortening
it to chase throughput misunderstands what it is for.

## Consequences

**The lock gained a `runId`.** This is the change that makes a clock possible at all. The lock's
purpose is to stop two runs colliding, and a scheduled wake is the same run continuing. Without an
identity on the lock, a tick reads its own fresh lock, concludes another run owns the repo, and exits
per §1.2. The loop would wake forever and never do anything.

**Staleness moved to `lastHeartbeat`.** A worker was observed running 27.6 minutes against a 30 minute
default stale window. Measured from `startedAt` a long dispatch can outlive its own lock while the
work is alive, and the next tick would then take a lock it already holds. That was a latent bug before
the clock existed; the clock would have made it routine.

**Dispatch gained an in-flight guard.** A timer can fire on top of live work, which a purely reactive
loop could never do. Two agents on one worktree corrupts the tree rather than merely wasting a
dispatch, so a tick that finds a `*_STARTED` stage with a live agent does nothing and re-arms.

**Startup split into a cold start and a tick.** A tick refreshes the lock, resumes the slots and
checks for unparked answers. It does not re-validate config or rebuild the queue, because rebuilding
mid-run would discard the progress held in `completed` and `parked`.

**Unparking became useful rather than ceremonial.** Polling for an operator's answer is only worth
specifying if something polls. A parked issue now rejoins the queue on its own once someone replies in
Linear.

**`maxIssuesPerRun` was removed.** It meant "issues before this invocation stops", which was
unambiguous only while a run was one invocation. Under a clock the boundary blurs, and the operator
asked to manage scale outside the skill instead. The loop's stop condition is now solely an empty
queue with nothing active.

## What this does not fix

None of it prevents an interrupt. A human stopping an agent still ends that agent, and the work it had
not yet committed is still lost. What changes is the cost: a halt no longer requires someone to notice
and restart the pipeline by hand.
