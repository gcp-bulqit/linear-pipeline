# Adopt the target repo's branch and worktree conventions

Branches are `<branchPrefix>/<issue-id-lowercased>-<slug>` — e.g. `agent/eng-123-add-health-probe`
— and worktrees live in `.claude/worktrees/<issue-id-lowercased>`. Pull requests target the repo's
actual default branch, which in the first target repo was `development`, not `main`.

The design originally specified `agent/ENG-42` branches and sibling worktrees at `../`. Inspecting
the first target repo showed dozens of existing worktrees under two conventions, an established branch format the
team already reads in PR lists, and `.claude/worktrees/` already excluded via `.git/info/exclude`.
Imposing a third convention would have made machine-authored branches conspicuous in exactly the
place where being unremarkable is the point: a human reviews these pull requests.

## Consequences

Machine-authored branches are not visually distinguishable from human ones. We accepted that
deliberately — provenance is available from the PR body and the Linear link, and legibility to
reviewers was judged worth more than filterability.

`baseBranch` is detected at setup rather than assumed, because assuming `main` would have been wrong
on the first repo we looked at.
