#!/usr/bin/env python3
"""mkslot.py <slot> [--recreate] -- PLANNING_COMPLETE -> WORKTREE_READY (SKILL.md §3, §7.1, §7.4)

For slot <slot>:
  1. derive the branch `<git.branchPrefix>/<id lowercased>-<slug of the title>` and the worktree
     `<git.worktreeDir>/<id lowercased>`; the title comes from the cached `.issues/<ID>/issue.md`,
     so this needs no network call to Linear
  2. `git fetch origin <git.baseBranch>`, then create the worktree and branch from
     `origin/<git.baseBranch>`; an existing worktree (a later attempt) is kept as it is
  3. reset the slot's database with slot_db.py, when `database` is a block in config
  4. write `stage: WORKTREE_READY`, `branch`, `worktree` and `database` to the slot, atomically

--recreate rebuilds a worktree that vanished from under a slot (SKILL.md §4, last row): it checks the
existing branch out again (from origin if it is not local), resets the database, and leaves the
slot's stage unchanged.

Prints one line: `WORKTREE_READY <slot> <ID> <branch> <worktree> db=<name|none>`.
Exit codes: 0 ok, 1 a git or database command failed, 2 usage, config or state error.

Run from the repo root. Standard library only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline_common import (  # noqa: E402
    PIPELINE_SCRIPTS, base_branch, fail, get_slot, issue_title, load_config, load_state,
    require_stage, run, save_state, slug,
)


def reset_db(cfg, n):
    if not isinstance(cfg.get("database"), dict):
        return "none"
    r = run([sys.executable, os.path.join(PIPELINE_SCRIPTS, "slot_db.py"), "reset", str(n)])
    if r.returncode:
        fail(1, "database reset failed: " + (r.stderr.strip() or f"exit {r.returncode}"))
    r = run([sys.executable, os.path.join(PIPELINE_SCRIPTS, "slot_db.py"), "name", str(n)])
    return r.stdout.strip() or "unknown"


def main(argv):
    recreate = "--recreate" in argv
    args = [a for a in argv if a != "--recreate"]
    if len(args) != 1:
        fail(2, "usage: mkslot.py <slot> [--recreate]")
    n = str(int(args[0])) if args[0].isdigit() else args[0]

    cfg = load_config()
    base = base_branch(cfg)
    state = load_state()
    slot = get_slot(state, n)
    if not recreate:
        require_stage(slot, "PLANNING_COMPLETE")
    issue = slot["issue"]

    branch = slot.get("branch") or f"{cfg['git']['branchPrefix']}/{issue.lower()}-{slug(issue_title(issue))}"
    tree = slot.get("worktree") or os.path.join(cfg["git"]["worktreeDir"], issue.lower())

    if not os.path.isdir(tree):
        r = run(["git", "fetch", "-q", "origin", base])
        if r.returncode:
            fail(1, f"git fetch origin {base} failed: {r.stderr.strip()}")
        branch_exists = run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}"]).returncode == 0
        if branch_exists:
            cmd = ["git", "worktree", "add", "-q", tree, branch]
        elif recreate and run(["git", "fetch", "-q", "origin", branch]).returncode == 0:
            cmd = ["git", "worktree", "add", "-q", "-b", branch, tree, f"origin/{branch}"]
        elif recreate:
            fail(2, f"--recreate: branch {branch} exists neither locally nor on origin")
        else:
            cmd = ["git", "worktree", "add", "-q", "-b", branch, tree, f"origin/{base}"]
        r = run(cmd)
        if r.returncode:
            fail(1, f"{' '.join(cmd)} failed: {r.stderr.strip()}")

    db = reset_db(cfg, n)

    state = load_state()  # re-read: never write back a stale copy
    slot = get_slot(state, n)
    slot.update({"branch": branch, "worktree": tree, "database": None if db == "none" else db})
    if not recreate:
        slot["stage"] = "WORKTREE_READY"
    save_state(state)
    print(f"WORKTREE_READY {n} {issue} {branch} {tree} db={db}" if not recreate
          else f"RECREATED {n} {issue} {branch} {tree} db={db}")


if __name__ == "__main__":
    main(sys.argv[1:])
