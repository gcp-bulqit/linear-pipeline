# Jev triage (optional add-on)

`jev_triage.py` sorts a backlog of Linear issues by whether a pull request alone can resolve them,
before any of them reach the pipeline. The core pipeline does not need it and does not call it.

## Read this first: it sends ticket text to a third party

This tool calls **TypeSafe's Jev model** (`https://api.typesafe.ai/v1/systemone`), a commercial,
paid, third-party API. For every issue it classifies, it sends:

- the issue's title, description (up to 3500 characters), workflow state, project and labels
- up to 8 comments (600 characters each); authors are replaced with pseudonyms ("person 1") unless
  you pass `--include-comment-authors`
- the repository description you supply with `--repository`
- code evidence computed locally: names of files and symbols the ticket mentions and whether they
  exist, and titles of pull requests and commits that name the issue

Do not run it over tickets your organisation does not allow to leave your systems. Check TypeSafe's
terms and your own data policy before you do.

It needs, in the environment:

| Variable | Used for |
|---|---|
| `LINEAR_API_KEY` | Reading issues (read scope is enough) |
| `TYPESAFE_API_KEY` | Calling Jev |

and `git`, an authenticated `gh` (for pull request evidence), and Python 3.8 or later. Standard
library only.

## What it does

For each issue it asks Jev a set of typed questions (is a repository change needed, is a step outside
the repository needed, is a decision still open, does production need investigating first, is it
already resolved, how large is it) and gets back probabilities. A policy in code, `bucket()`, turns
those into one of `pure_pr`, `likely_pr_review`, `pr_plus_ops`, `needs_decision`, `not_pr` or
`already_resolved`. The thresholds are starting points, not truths; change `bucket()` and re-run with
`--rebucket` to re-apply it to stored answers without calling the API again.

## Use

From the target repository's root:

```
J=/path/to/linear-pipeline/addons/jev-triage
cp $J/repository.example.json repository.json   # then describe YOUR repository
python3 $J/jev_triage.py --repository repository.json --assignee "Pipeline Bot" --states Todo,Backlog
python3 $J/jev_triage.py --repository repository.json --ids ENG-101,ENG-102
python3 $J/jev_triage.py --rebucket --emit-triage
```

Outputs go to `--out` (default `.agent/jev-triage/`; add it to `.gitignore`, since it holds ticket
text): `results.json` with the raw answers, and `report.md` with one row per issue.

Options that adapt it to a repository, all optional:

| Option | Default | Notes |
|---|---|---|
| `--assignee` | `linear.user` from `.agent/config.json` | Linear user name to pull issues for. |
| `--base` | `git.baseBranch`, else `main` | Branch the code evidence is read from. |
| `--pathspec` | whole repository | Limit the symbol search, e.g. `--pathspec src --pathspec lib`. |
| `--pr-limit` | `1000` | How many recent pull requests to index for evidence. |
| `--ignore-comment` | `linear.unparkIgnorePatterns` | Regex; matching comments are dropped (e.g. a feedback tool's status-sync comments). |
| `--cut-description` | none | Regex; the description is cut at its first match (e.g. session metadata an intake tool appends). |

## Feeding the pipeline

Two ways, both explicit:

- `--emit-triage` merges each bucket into `.agent/triage.json`, the cache the pipeline's
  `linear.codeChangesOnly` reads: `pure_pr` becomes `CODE`, `not_pr` and `already_resolved` become
  `NOT_CODE`, everything else `AMBIGUOUS`. Rows already in the file are never overwritten.
- Copy the ids you accept from `report.md` into an `ingestSources[].ids` list in
  `.agent/config.json`, so the pipeline works exactly that shortlist.

Review the report before either. A classifier's bucket is a suggestion about a ticket a person wrote;
the pipeline will act on it.

## Evaluating it on your own history

`--eval labels.json` scores the buckets against issues whose outcome you know:
`{"positive": [ids that shipped as a PR], "negative": [ids closed with no code]}`. Each issue is judged
on the comments that existed before work began, with links from the issue id to pull requests and
commits withheld, so the label cannot leak into what the model sees.
