# Writing the pull request

Read this together with the repository's own template, at the path your dispatch names
(`pr.templatePath`, by default `.github/pull_request_template.md`). When that file exists it is the
authority on structure, and this one is how to fill it from a pipeline run. When it does not, use the
fallback template at the end of this file.

You produce two artifacts:

- `.issues/<ISSUE_ID>/pr-title.txt` — one line, no trailing newline needed
- `.issues/<ISSUE_ID>/pr-body.md` — the completed template

## The title is the permanent commit message

Where the repository squash-merges — check with `git log --format='%p' -5 <base>`; single-parent
commits mean it does — every commit on the branch collapses at merge and **the pull request title
becomes the one subject that survives in history.** The worker's step subjects and your docs subject
all disappear. It is the most consequential line in the run, and it is yours.

Your dispatch names the title format (`pr.titleFormat`). `{id}` is the issue ID and `{summary}` is
yours to write. With `[{id}] {summary}`:

```
[ENG-123] Imperative, user-facing summary
```

- Fill the format exactly; the supervisor checks the title against it before pushing.
- Imperative mood, capitalized, and short enough to read in a list — aim for 50 characters of
  summary, and treat that as a ceiling.
- **A summary of the change, not the ticket's title.** The ticket names a request; you have read the
  diff, the plan and the reviews, so you know what actually shipped. "Login button broken" is the
  request. "Restore login on Safari 17" is the change.
- Frame it as what someone can do now. Same rules as a commit subject: no tooling prefix, no
  before-and-after contrast, and attribution only as the repository's policy allows (your dispatch
  names it; under `none`, none at all).

## Filling the template

Keep every heading the template gives you and their order. Delete only sections that genuinely do not
apply, and delete the template's HTML comments. Templates differ; the guidance below covers the
sections most of them have, under whatever name the template uses.

**Summary** — prose, a few sentences. Lead with the problem in the affected user's terms and the
concrete symptom, then what this delivers. Draw on the plan's `## Goal` and `## Approach` and the
discovery findings. Link the spec or docs that define the intended behaviour when the findings cite
one.

**Tickets / links** — the Linear ID and URL from `issue.md`. If the template has a project or
milestone field, fill it only when the ticket names one; otherwise delete it.

**What changed** — behaviour after this lands, grouped under `###` subsections by area, not a file
list. Derive the areas from the diff: a user-facing screen, a billing path, an admin form, a
background job. Say what the system now does and why that is correct.

Carry **every advisory review finding from every attempt** into this section, each with its
`path:line`. Give them their own `### Advisory review findings` subsection. The reviewer wrote them
for whoever merges, and this body is the only route they take to reach that person.

Record any known-flake exemption the gate used (the gate log names it), so the exception is never
silent.

**Scope / out of scope** — what was deliberately left out, from the plan's `## Out of scope`, plus any
advisory finding a human may want to act on separately and anything ops or support should know. Worth
writing even when short.

**Test coverage** — automated coverage, grouped by area. Name what the new and existing tests exercise
and what they deliberately do not. This is where the run's real evidence belongs: the worker's
targeted tests per step, and the verify gate's entries with their results. Both are things that
actually happened, so both can be stated as fact.

## Manual QA: include the section, invent nothing

Many templates ask for manual verification through the real UI, with evidence: screenshots, record
ids, page text, network responses. **This pipeline performs no manual QA.** No agent in it opens a
browser or exercises a flow.

If the template has such a section, keep it. Write it as a handoff rather than a report:

- **Scope** — name the surfaces this change touches and states a human should exercise. You know them
  from the diff and the reviewer's blast radius.
- **The case table** — one row per case a human should check. Fill `Case` and `Check` from what the
  change can affect. Put `Not performed` in `Result`, and in `Evidence` name what would count as
  proof, so the person running it knows what to capture.
- **Verdict** — state plainly that no manual QA was performed in this run, and that the cases above
  are outstanding.

An empty table with a note is worse than this; a filled table with evidence nobody observed is far
worse than both. Evidence you did not see is fabricated evidence, and a reviewer will trust it — which
is exactly why any repository that asks for QA evidence needs it to be real.

## Fallback template

When the repository has no template, write this:

```markdown
## Summary
<the problem in the affected user's terms, then what this delivers>

Ticket: <ISSUE_ID> <url>

## What changed
### <area>
<behaviour after this lands>

### Advisory review findings
- `path:line` — <finding>   (or "None.")

## Out of scope
<from the plan, plus anything ops or support should know>

## Test coverage
<targeted tests per step; each verify entry and its result>

## Manual QA
Not performed by the pipeline. Cases a human should check:

| Case | Check | Result | Evidence |
|---|---|---|---|
| <case> | <what to look at> | Not performed | <what would count as proof> |
```

## Before you finish

- Every heading from the template is present, or deliberately deleted.
- No HTML comments remain.
- Every advisory finding from every attempt appears.
- Nothing in the QA section claims an observation the run did not make.
- The title fills `pr.titleFormat`, names the change, and reads as a commit subject.
