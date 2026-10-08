# `.agent/config.json` — Field Reference

> Human reference. The supervisor's **runtime** validation checklist lives in its `SKILL.md`; this
> document explains the fields, their defaults, and why they exist. The two overlap only on field
> names.

Committed to the target repo (see ADR-0009 for what is committed and what is ignored). Written by
the supervisor's **setup mode** on first run, then edited by hand.

JSON has no comments, so every explanation lives here. Keys this document does not list are ignored
by the supervisor and the scripts; you may use them (a `note` on an ingest source, say) to annotate
the file for people. They are never instructions: the pipeline acts only on documented fields.

## Example

A complete example, covering every option, ships as `examples/config.example.json` in the framework
repository. It is written for a hypothetical pnpm + Turborepo monorepo (`acme/webapp`) with a Postgres
integration suite, and uses placeholder names throughout. The short form below is the minimum a
single-slot run needs:

```json
{
  "linear": {
    "user": "Pipeline Bot",
    "mcpServer": "linear-bot",
    "reviewState": "In Review"
  },
  "verify": [
    { "name": "lint",      "command": "pnpm lint" },
    { "name": "typecheck", "command": "pnpm typecheck" },
    { "name": "test",      "command": "pnpm test" }
  ]
}
```

The pipeline is not tied to Node. A Python repository's `verify` could as well be:

```json
[
  { "name": "lint",  "command": "ruff check ." },
  { "name": "types", "command": "mypy src" },
  { "name": "test",  "command": "pytest -q" }
]
```

## Fields

### `linear`

| Field | Required | Default | Notes |
|---|---|---|---|
| `user` | **FATAL** | — | The **Pipeline Bot** identity, as Linear names the user. Issues assigned to it are the intake filter, and §1.4 checks the MCP entry is authenticated as it. |
| `mcpServer` | **FATAL** | — | Name of the MCP server entry authenticated as the bot. See ADR-0012. |
| `ingestState` | no | `"Todo"` | Linear workflow state to pull from. |
| `ingestLabel` | no | `null` | Optional additional label filter. `null` means no label requirement. |
| `reviewState` | no | none | Workflow state the issue moves to once its pull request is open, for example `In Review`. Spell it exactly as Linear does. Omit it and the issue stays In Progress, which means nothing tells the team the work is waiting on them. |
| `ingestSources` | no | none | Several intake queries instead of one. See below. |
| `codeChangesOnly` | no | none | Queue only issues that would produce a commit here. See below. |
| `unparkIgnorePatterns` | no | `[]` | Regular expressions (Python syntax). A comment whose text matches one never unparks an issue. |

`reviewState` is optional rather than fatal because a repository may have no such column, and a
pipeline that refuses to run over a missing workflow state would be worse than one that leaves the
issue where it is. It is the field most worth setting anyway: the status move is what puts finished
work on a human's board, and a comment alone is easy to miss.

`mcpServer` is fatal-if-missing rather than defaulted on purpose: defaulting it would silently fall
back to the operator's own Linear identity, which is the exact failure ADR-0012 exists to prevent.

`unparkIgnorePatterns` exists for integrations that comment under a human's account, such as a
feedback tool that writes `changed feedback status to "Done"` whenever someone moves a report. Such a
comment has a human author and a fresh timestamp, so without a pattern it would release a parked issue
with no answer in it. Example: `["^changed feedback status to \".*\" in \\w+$"]`.

#### `linear.ingestSources`

An array. When present it **replaces** `user` / `ingestState` / `ingestLabel` as the intake query;
each entry is its own query, and the results are merged, de-duplicated and ordered by priority.

| Field | Required | Notes |
|---|---|---|
| `name` | no | A label for the close-out summary. |
| `user` | **FATAL** | Assignee to pull from. Any user, not only the bot: an operator can feed their own tickets in. |
| `state` | **FATAL** | Workflow state to pull from. |
| `label` | no | Label filter for this source. |
| `priority` | no | `null`, or a list of Linear priority numbers to accept (`1` urgent, `2` high, `3` medium, `4` low, `0` none). |
| `ids` | no | Take only these issues (still only when they match `user` and `state`), at any priority. Useful for a reviewed shortlist. |

Whatever the source, every Linear write still goes through `mcpServer` as the Pipeline Bot. An issue
assigned to a person and pulled in by a source gets the bot's comments, never comments in that
person's name.

A source whose tickets carry ongoing human conversation, or that are not all code tasks, is worth
pairing with `codeChangesOnly`.

#### `linear.codeChangesOnly`

```json
{ "enabled": true, "onAmbiguous": "skip" }
```

| Field | Default | Notes |
|---|---|---|
| `enabled` | `false` | When true, an issue is queued only if resolving it would produce a commit in this repository. |
| `onAmbiguous` | `"skip"` | `"skip"` leaves an `AMBIGUOUS` issue alone and lists it in the close-out. `"queue"` queues it and lets discovery decide; discovery returns `STATUS=NOT_CODE` when no change here is needed. |

Issues classified `NOT_CODE` (or skipped as `AMBIGUOUS`) stay in their ingest state, are not queued,
and receive **no Linear comment of any kind**. Billing chores, third-party dashboard settings, one-off
data fixes, questions and notices are the usual cases. The silence is the point: a team that assigns
mixed work to a queue should not find a machine commenting on its non-code tickets.

The classification is cached in `.agent/triage.json` (gitignored), an object keyed by issue id:

```json
{
  "ENG-130": { "verdict": "CODE", "reason": "names a component in src/", "by": "supervisor", "at": "2026-01-14T09:00:00Z" },
  "ENG-131": { "verdict": "NOT_CODE", "reason": "renew a hosting subscription", "by": "supervisor", "at": "2026-01-14T09:00:00Z" }
}
```

`verdict` is `CODE`, `NOT_CODE` or `AMBIGUOUS`. The supervisor classifies from queue metadata only
(title, labels, project), never the ticket body. A row is reused on every later run; delete it to have
the issue re-classified. An external classifier may write rows too (`by` names it); the optional
`addons/jev-triage` tool is one.

### `verify`

An **ordered array** of `{ name, command }`. Run in order; stop at the first failure. Not a fixed
set of three — many repos separate typecheck from lint, which is why `verify` is a list rather than
fixed `build` / `test` / `lint` fields.

| Field | Required | Notes |
|---|---|---|
| `verify` | **FATAL** | Must be a non-empty array. |
| `verify[].name` | **FATAL** | Named so a failure report says *which* gate failed. |
| `verify[].command` | **FATAL** | Run from the worktree root, through the shell. |

**Order them cheapest-first.** A lint error should fail in seconds, not after a full test run. An
absent or empty `verify` is a fatal setup error, never "this repo has no checks".

### Mirror CI exactly

**Copy the commands out of the repository's CI workflow, verbatim, one entry per command.** Not the
convenience wrapper a developer types — the literal invocation the pull request will be judged by.

The gate exists to predict CI. Every difference between the two is a way for the gate to be wrong in
one of two expensive directions: it passes and CI fails, so a human finds the problem after the
pipeline has declared itself done; or it fails and CI would have passed, so an attempt is burned on
something that was never broken.

This is not hypothetical. In practice, a gate that ran a convenience wrapper (`just test-unit`) while
CI ran the underlying command (`pnpm turbo run test ...`) produced a failure CI did not — different
runner, different parallelism, different failing set each run. The supervisor spent an attempt
establishing that the failure was suite nondeterminism rather than a regression, and the whole
investigation existed only because the two commands were not the same command.

A CI job that runs two commands becomes **two entries**, so a failure names which one. A job with a
setup step keeps the setup in the same entry, chained with `&&`, so the entry is self-contained.

**Dropping an entry is a real choice.** An expensive one — a suite needing a live database, say — can
be left out, and the pipeline will then hand you pull requests whose CI status it could not predict.
Make that trade deliberately rather than by omission.

Note the overlap with commit hooks (ADR-0010): if the repo's pre-commit hooks (lefthook, husky,
pre-commit) run lint and typecheck on every worker commit, then by the time the supervisor's gate runs
those entries are usually cache hits. They stay in the list because the gate must be authoritative and
independent of hook configuration.

Formatting deserves its own entry wherever CI checks it. A repo whose lint job runs only a linter will
merge unformatted code, and neither the hooks nor the gate will have said a word.

### `verifyKnownFlakes`

Optional, and only effective when `gate.flakeParser` names a parser. Each entry is one test file the
operator has accepted as flaky on the base branch. A gate step whose only failures are in these files
passes if each file passes on an isolated re-run (see SKILL.md §7.2). Added and removed by the operator
only; the supervisor never adds one.

| Field | Required | Notes |
|---|---|---|
| `step` | yes | The `verify[].name` this exemption applies to. |
| `kind` | no | `testFailure` (default) matches a failed test in `file`. `unhandledError` matches an unhandled error the runner attributes to `file` while every test passed (Vitest prints "This error originated in ..."). |
| `package` | yes | The workspace package name as the runner prints it in its output prefix (Turborepo prints `<package>:<task>:`). |
| `packageDir` | yes | Directory the isolated re-run runs in, relative to the worktree root. |
| `file` | yes | The test file, as the runner prints it, relative to `packageDir`. |
| `rerunCommand` | no | The isolated re-run. `{file}` is substituted. Default for the `vitest` parser: `npx vitest run {file}`. |
| `exemptIfBranchTouches` | no | Globs. A branch whose diff against the base touches any of them gets no exception from this entry, because there the failure may be the branch's own. |
| `why`, `approved`, `removeWhen` | recommended | For people: the evidence, who approved it and when, and the condition that retires it. |

### `gate`

How `scripts/gate.py` prepares and runs the verify gate. All optional.

| Field | Default | Notes |
|---|---|---|
| `preCommands` | `[]` | Shell commands run in the worktree before the first `verify` entry, e.g. `pnpm install --frozen-lockfile --prefer-offline` so a fresh worktree has dependencies. A failure stops the gate with exit 4. |
| `perSlotEnv` | `{}` | Variables exported for the gate, with `{root}` (repo root, absolute) and `{slot}` substituted. Use it for build caches: `{"TURBO_CACHE_DIR": "{root}/.agent/cache/s{slot}"}`. A shared cache can replay a sibling worktree's pass and turn the gate into a no-op. |
| `unsetEnv` | `[]` | Variables removed from the gate's environment, e.g. `["PGHOST", "PGPORT"]`, which libpq prefers over the URL. |
| `maxLoadAvg` | `null` | Wait until the one-minute load average is below this before starting. Workers running builds beside the gate load the machine as much as a second gate would. |
| `loadWaitSeconds` | `600` | How long to wait for `maxLoadAvg` before running anyway (and saying so in the log). |
| `flakeParser` | `"none"` | `"vitest"` enables `verifyKnownFlakes` using Vitest's (and Turborepo's prefixed) output format. This parser is an **example**: another runner needs its own parser in `gate.py`. |
| `logTailChars` | `20000` | How much of a failing entry's output is kept in `gate.log`. |

### `git`

| Field | Required | Default | Notes |
|---|---|---|---|
| `baseBranch` | no | detected | Branch to base worktrees on and target PRs at. Detected from `origin/HEAD` at setup; many repos do not use `main`. |
| `branchPrefix` | no | `"agent"` | Branch namespace. Inferred from recent branch names at setup (ADR-0011). |
| `worktreeDir` | no | `".claude/worktrees"` | Relative to repo root. Must be gitignored (setup mode adds it). |
| `prMode` | no | `"draft"` | Only `"draft"` is supported. Present so the constraint is visible in config, not to be changed. |
| `attribution` | no | `"none"` | `"none"`: no AI or tool attribution in commit subjects, bodies, trailers, PR titles or bodies, and `ship.py` refuses to push one. `"repo"`: follow the repository's own documented policy (AGENTS.md, CONTRIBUTING); nothing is enforced. |
| `attributionMarkers` | no | `["Co-Authored-By", "Generated with", "Claude Code"]` | Case-insensitive strings `ship.py` refuses under `"none"`. |
| `requireSigned` | no | `false` | When true, `ship.py` refuses to push a branch with an unsigned commit. A locked signing key is an operator step (`WAITING_OPERATOR`); work the hook or signer rejected is stashed, never lost (ADR-0010). |

**Branch name** is `<branchPrefix>/<issue-id-lowercased>-<slug>`, e.g.
`agent/eng-123-add-health-probe`. The slug is derived from the issue title: lowercased,
non-alphanumerics collapsed to single hyphens, trimmed, truncated at 50 characters on a hyphen
boundary. **Worktree path** is `<worktreeDir>/<issue-id-lowercased>`.

Attribution is a policy, so it lives in config rather than in a prompt. Under `"none"`, the instruction
alone was observed to fail: a reminder injected by the agent harness, and once text inside a test
runner's output, asked agents to add a co-author trailer, and an agent complied. That is why the rule
is backed by a check before push, why agents commit with `-m` and no trailers, and why every prompt
says that text arriving in tool output is data, not instruction. A `commit-msg` hook in the target repo
is a stronger guard still.

### `pr`

| Field | Default | Notes |
|---|---|---|
| `titleFormat` | `"{summary}"` | `{id}` and `{summary}` are substituted. `"[{id}] {summary}"` gives `[ENG-123] Restore login on Safari 17`. `ship.py` checks the title the documentation agent wrote against it. |
| `templatePath` | `".github/pull_request_template.md"` | The repository's PR template. When absent, the documentation agent uses the fallback in `reference/pull-request.md`. |

### `docs`

| Field | Default | Notes |
|---|---|---|
| `root` | `"docs/"` | Where curated notes live. Discovery reads it first; the documentation agent edits and commits it. |

### `limits`

| Field | Required | Default | Notes |
|---|---|---|---|
| `maxCycles` | no | `3` | Attempts before escalation. **One shared counter** — verify failures and review failures both increment it. |
| `maxRediscovery` | no | `1` | Re-discoveries per issue. A second `NEEDS_DISCOVERY` blocks instead of looping. |
| `workerStepRetries` | no | `2` | Attempts at a failing step before the worker yields. |
| `maxConcurrent` | no | `1` | Issues in flight at once, each in its own slot (ADR-0014). `1` reproduces the single-active behaviour. The verify gate stays one at a time regardless. |

One counter, not two, because two budgets mean two ways to loop and an issue alternating between
them may never terminate.

### `admission`

| Field | Default | Notes |
|---|---|---|
| `serializeMigrations` | `true` | At most one slot past discovery may carry a migration. Turn off only when migrations are named by timestamp, so two branches cannot take the same number. |

### `database`

Required when `limits.maxConcurrent` is above 1: either this block, or an explicit `null` meaning "no
verify entry touches a database, so slots need no isolation". Each slot gets its own local database so
that two gates never migrate or truncate the same tables (ADR-0014).

The shipped adapter, `scripts/slot_db.py`, is for **Postgres** (it needs `psql`, `pg_dump` and
`pg_restore` on `PATH`, and Postgres 13 or later for `DROP DATABASE ... WITH (FORCE)`). Another engine
needs its own adapter with the same commands.

| Field | Required | Default | Notes |
|---|---|---|---|
| `baseUrlEnv` | no | `DB_URL` | Environment variable holding the operator's local database URL. Only its host, port and credentials are reused; the database name is replaced. Must point at localhost. |
| `urlEnvNames` | no | `[baseUrlEnv]` | Every variable the slot URL is exported as, for the gate and the worker, e.g. `["DB_URL", "DATABASE_URL"]` when different tools read different names. |
| `baseDatabase` | **yes, in the block** | — | The migrated local database the template is cloned from, e.g. `app`. |
| `slotTemplate` | no | `<baseDatabase>_template` | Template every slot database is cloned from. Rebuilt by `scripts/slot_db.py template`. |
| `slotPrefix` | no | `<baseDatabase>_s` | Slot `n`'s database is `<slotPrefix><n>`, e.g. `app_s1`. |
| `siblingSuffixes` | no | `[]` | Sibling databases your test harness derives from the URL, e.g. `["_test"]`. Each is reset with its slot. |
| `siblingMigrateCommand` | no | `null` | Run by `gate.py` against each sibling before the first verify entry, with the URL variables pointing at the sibling. E.g. `pnpm --filter @acme/db migrate`. |
| `migrationsHighWaterSql` | no | `null` | Optional query `slot_db.py template` runs on the new template to report how far it is migrated, e.g. `SELECT max(created_at) FROM drizzle.__drizzle_migrations` for Drizzle. A failure is reported as "unknown", never as a failed rebuild. |

`scripts/slot_db.py` refuses any URL whose host is not `localhost`, `127.0.0.1` or `::1`. It never
touches a remote database.

### `clock`

| Field | Default | Notes |
|---|---|---|
| `minSeconds` | `1200` | Earliest fallback wake after a dispatch (ADR-0013). |
| `maxSeconds` | `1800` | Latest. The wake notices a broken notification chain; it is not a scheduler, so do not shorten it to chase throughput. |

### `lock`

| Field | Required | Default | Notes |
|---|---|---|---|
| `staleAfterMinutes` | no | `30` | After this, a lock held by **another** run is cleared and this run proceeds. |

The lock file itself holds `runId`, `pid`, `host`, `startedAt` and `lastHeartbeat`. Two of those carry
weight.

`runId` separates a rival run from your own scheduled wake. Without it, a tick reads its own fresh
lock, concludes someone else owns the repo, and exits; the loop would tick forever and never work.

`lastHeartbeat` is what staleness is measured against, never `startedAt`. A single worker can run 30
minutes, the whole of the default window, so measuring from the start of the run would let a lock
expire while the work behind it is alive. Every tick refreshes it.

**Not optional in effect.** A run killed by the usage limit never releases its lock, so the stale
path is the normal path. A lock with no stale timeout wedges the system permanently on its first
quota kill.

### `models`

Per-**leaf-agent** `model` and `effort`. Both are real `.claude/agents/*.md` frontmatter fields, and
both are tunable: the shipped split (the expensive model for the planner and reviewer, where judgement
lives; the cheaper one for discovery, the worker and documentation) is a starting point.

There is **no `supervisor` entry**: the supervisor is a skill, and `effort` is an agent-only
frontmatter field, so it runs on whatever model the operator's session is using. If it matters, the
operator sets it with `/model` or `--model` before invoking.

Values here override the defaults baked into each agent file. Omit the whole `models` object to use
the agent files as written.

## Environment

Credentials live in the environment, never in this file.

| Variable | Required | Notes |
|---|---|---|
| `LINEAR_API_KEY` | **FATAL** | The Pipeline Bot's Linear API key, **read scope only**. Used by `scripts/fetch_issue.py` to write a ticket body to a file without it entering the supervisor's context. |
| `database.baseUrlEnv` (e.g. `DB_URL`) | when `database` is a block | The operator's **local** database URL. The scripts reuse its host, port and credentials. |

**The key is not a config field, and must never become one.** `.agent/config.json` is committed, so a
key placed here would be published to everyone with repository access.

Read scope suffices because the script only reads. Every Linear *write* goes through the bot's MCP
entry, so the key's identity never authors anything — which also means it can be rotated without
touching the unpark check that compares comment authors.

Two credentials, one bot, each for a different mechanical reason: the MCP entry supplies a write
identity; the key supplies a read path that bypasses the context window.

## Failure classes

| Class | Meaning | Behaviour |
|---|---|---|
| **FATAL** | The system cannot run correctly and would fail confusingly later. | Stop before touching Linear or git. Print which field, and the setup-mode hint. |
| **default** | Absent is a legitimate choice. | Apply the default silently. |

Nothing is inferred at runtime. A missing verify command is never treated as "no checks needed" —
that would silently disable the only half of "done" that cannot be argued with.

## Setup mode

When `.agent/config.json` is absent, the supervisor enters setup mode instead of running:

1. Detect candidate verify commands — the CI workflow first, then `package.json` scripts, `Makefile`,
   `Justfile` and the like — and propose an ordered list.
2. Detect `baseBranch` from `origin/HEAD`.
3. Detect an existing worktree convention; propose `.claude/worktrees` if none.
4. Infer `branchPrefix`, `requireSigned` and `pr.titleFormat` from history; ask for `attribution`.
5. Propose `maxConcurrent: 1`, and a `database` block or `null` if the operator wants more.
6. Resolve the Linear bot user, confirm the MCP server entry exists, and confirm it is authenticated
   as the bot.
7. Confirm everything with the operator.
8. Write `.agent/config.json`; add the pipeline's runtime files (`.agent/state.json`,
   `.agent/state.json.tmp`, `.agent/queue.json`, `.agent/lock`, `.agent/triage.json`, `.agent/cache/`,
   `.issues/`, the worktree directory, `__pycache__/`, `.env`) to `.gitignore` if absent.
9. **Stop.** Do not begin a pipeline run in the same invocation — setup is a decision point, and the
   operator should see the config before work starts against it.
